"""Flujo del agente como grafo con estado de LangGraph (SPEC 7.1, RF-21 a RF-26).

Es un único grafo, no un sistema multiagente. Recorre las secciones en el orden del formato;
cada sección se genera y el flujo se detiene (`interrupt`) hasta que el docente la apruebe, la
edite o pida regenerarla con una indicación. Al final verifica el sílabo completo: si hay
hallazgos bloqueantes, se detiene para que el docente reabra la sección afectada.

El estado del grafo se guarda en un punto de control (SQLite) por sílabo, de modo que el
docente puede cerrar la sesión y retomarla después (RF-26).
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from syllabusai.agent.servicio import ErrorServicio, ServicioSilabos

ACCIONES_REVISION = ("aprobar", "editar", "regenerar")
ACCIONES_CORRECCION = ("reabrir", "verificar")


class EstadoAgente(TypedDict, total=False):
    silabo_id: int
    clave: str | None
    indicacion: str | None
    error: str | None


def construir_grafo(servicio: ServicioSilabos) -> StateGraph:
    def siguiente(estado: EstadoAgente) -> Command:
        secciones = servicio.estado(estado["silabo_id"])["secciones"]
        for s in secciones:
            if s["estado"] == "aprobada":
                continue
            # Una sección que ya tiene propuesta (p. ej. al retomar) va directo a revisión.
            destino = "generar" if s["estado"] == "pendiente" else "revision"
            return Command(goto=destino, update={"clave": s["clave"], "indicacion": None, "error": None})
        return Command(goto="verificar", update={"clave": None})

    def generar(estado: EstadoAgente) -> Command:
        try:
            servicio.generar_seccion(estado["silabo_id"], estado["clave"], estado.get("indicacion"))
            return Command(goto="revision", update={"error": None})
        except ErrorServicio as error:
            return Command(goto="revision", update={"error": str(error)})

    def revision(estado: EstadoAgente) -> Command:
        decision: dict[str, Any] = interrupt({
            "tipo": "revision_seccion", "clave": estado["clave"], "error": estado.get("error"),
            "acciones": list(ACCIONES_REVISION),
        })
        silabo_id, clave = estado["silabo_id"], estado["clave"]
        accion = decision.get("accion")
        try:
            if accion == "regenerar":
                return Command(goto="generar", update={"indicacion": decision.get("indicacion")})
            if accion == "editar":
                servicio.editar_seccion(silabo_id, clave, decision["contenido"])
                return Command(goto="revision", update={"error": None})
            if accion == "aprobar":
                if decision.get("contenido") is not None:
                    servicio.editar_seccion(silabo_id, clave, decision["contenido"])
                servicio.aprobar_seccion(silabo_id, clave)
                return Command(goto="siguiente", update={"error": None})
            raise ErrorServicio(f"Acción no reconocida: {accion!r}")
        except (ErrorServicio, KeyError) as error:
            return Command(goto="revision", update={"error": str(error)})

    def verificar(estado: EstadoAgente) -> Command:
        hallazgos = servicio.verificar(estado["silabo_id"])
        bloqueantes = [h for h in hallazgos if h["severidad"] == "bloqueante" and not h["resuelto"]]
        if not bloqueantes:
            return Command(goto=END, update={"error": None})
        decision = interrupt({
            "tipo": "correccion", "hallazgos": bloqueantes, "error": estado.get("error"),
            "acciones": list(ACCIONES_CORRECCION),
        })
        if decision.get("accion") == "reabrir":
            try:
                servicio.reabrir_seccion(estado["silabo_id"], decision["clave"])
                return Command(goto="revision", update={"clave": decision["clave"], "error": None})
            except (ErrorServicio, KeyError) as error:
                return Command(goto="verificar", update={"error": str(error)})
        return Command(goto="verificar", update={"error": None})

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("siguiente", siguiente, destinations=("generar", "revision", "verificar"))
    grafo.add_node("generar", generar, destinations=("revision",))
    grafo.add_node("revision", revision, destinations=("generar", "revision", "siguiente"))
    grafo.add_node("verificar", verificar, destinations=("revision", "verificar", END))
    grafo.add_edge(START, "siguiente")
    return grafo


class Orquestador:
    """Inicia y reanuda el grafo de cada sílabo; expone la pausa pendiente a la API y la UI."""

    def __init__(self, servicio: ServicioSilabos, checkpointer):
        self.servicio = servicio
        self.grafo = construir_grafo(servicio).compile(checkpointer=checkpointer)

    @staticmethod
    def _config(silabo_id: int) -> dict:
        return {"configurable": {"thread_id": f"silabo-{silabo_id}"}}

    def pendiente(self, silabo_id: int) -> dict:
        """La pausa en que está el flujo, o `{"tipo": "terminado"}` si no hay ninguna."""
        estado = self.grafo.get_state(self._config(silabo_id))
        for tarea in estado.tasks:
            for pausa in tarea.interrupts:
                return dict(pausa.value)
        if not estado.values:
            return {"tipo": "sin_iniciar"}
        return {"tipo": "terminado"}

    def iniciar(self, silabo_id: int) -> dict:
        """Arranca (o rearranca tras una reapertura) el flujo hasta la siguiente pausa."""
        if self.pendiente(silabo_id)["tipo"] in ("revision_seccion", "correccion"):
            return self.pendiente(silabo_id)
        self.grafo.invoke({"silabo_id": silabo_id}, self._config(silabo_id))
        return self.pendiente(silabo_id)

    def reanudar(self, silabo_id: int, decision: dict[str, Any]) -> dict:
        pausa = self.pendiente(silabo_id)
        validas = {"revision_seccion": ACCIONES_REVISION, "correccion": ACCIONES_CORRECCION}
        if pausa["tipo"] not in validas:
            raise ErrorServicio("El flujo no está esperando una decisión del docente")
        if decision.get("accion") not in validas[pausa["tipo"]]:
            raise ErrorServicio(f"En esta pausa las acciones válidas son: {validas[pausa['tipo']]}")
        self.grafo.invoke(Command(resume=decision), self._config(silabo_id))
        return self.pendiente(silabo_id)

    def reabrir(self, silabo_id: int, clave: str) -> dict:
        """Reabre una sección aprobada desde cualquier punto del flujo."""
        pausa = self.pendiente(silabo_id)
        if pausa["tipo"] == "correccion":
            return self.reanudar(silabo_id, {"accion": "reabrir", "clave": clave})
        if pausa["tipo"] == "revision_seccion":
            raise ErrorServicio("Termine primero la revisión de la sección en curso")
        self.servicio.reabrir_seccion(silabo_id, clave)
        return self.iniciar(silabo_id)

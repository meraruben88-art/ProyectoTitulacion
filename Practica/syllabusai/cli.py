"""Línea de comandos de SyllabusAI.

    syllabusai ejemplo                        corpus de ejemplo + usuarios demo, listo para probar
    syllabusai init --correo ... --clave ...  crea la base y el administrador del corpus
    syllabusai usuario ...                    crea un usuario (docente, admin_corpus, evaluador)
    syllabusai catalogo RUTA                  importa la ficha curricular de las asignaturas
    syllabusai ingestar MANIFIESTO            registra, extrae, segmenta e indexa (RF-07)
    syllabusai buscar "consulta"              consulta directa al recuperador
    syllabusai demo --asignatura ITI-501      flujo completo aprobando cada sección y exportando
    syllabusai metricas [--vllm]              exporta eventos a CSV/JSON (RF-54)
    syllabusai evaluar                        evaluación completa (SPEC 11) en eval/resultados
    syllabusai api | syllabusai ui            levanta la API (FastAPI) o la interfaz (Streamlit)
    syllabusai mallas [--reextraer]           importa las mallas del CES de la carpeta MALLAS
    syllabusai admin --correo ... --nombre ...  crea (o restablece) una cuenta de administrador
    syllabusai reindexar                      reprocesa el corpus (al cambiar de embeddings)
    syllabusai web                            página web completa en http://127.0.0.1:8080
"""

import argparse
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from syllabusai.config import RAIZ, cargar_config
from syllabusai.db.modelos import Asignatura, Rol, TipoDocumento, Usuario


def _contenedor(args):
    from syllabusai.contenedor import crear_contenedor

    return crear_contenedor(cargar_config(args.config))


def _admin(sesion) -> Usuario:
    admin = sesion.scalar(select(Usuario).where(Usuario.rol == Rol.ADMIN_CORPUS).order_by(Usuario.id))
    if admin is None:
        sys.exit("No hay administrador del corpus: ejecute `syllabusai init` o `syllabusai ejemplo`.")
    return admin


def cmd_init(args) -> None:
    from syllabusai.seguridad import crear_usuario

    c = _contenedor(args)
    with c.fabrica() as sesion:
        crear_usuario(sesion, args.nombre, args.correo, args.clave, Rol.ADMIN_CORPUS)
        sesion.commit()
    print(f"Base creada y administrador «{args.correo}» registrado.")


def cmd_usuario(args) -> None:
    from syllabusai.seguridad import crear_usuario

    c = _contenedor(args)
    with c.fabrica() as sesion:
        usuario = crear_usuario(sesion, args.nombre, args.correo, args.clave, Rol(args.rol))
        sesion.commit()
        print(f"Usuario {usuario.id} creado: {usuario.correo} ({usuario.rol}).")


def cmd_catalogo(args) -> None:
    from syllabusai.ingest.catalogo import importar_catalogo

    c = _contenedor(args)
    with c.fabrica() as sesion:
        asignaturas = importar_catalogo(sesion, args.ruta)
        sesion.commit()
        for a in asignaturas:
            print(f"  {a.codigo}  {a.nombre}  ({a.horas} h)")


def cmd_ingestar(args) -> None:
    from syllabusai.ingest.pipeline import cargar_manifiesto, ingestar_manifiesto

    c = _contenedor(args)
    with c.fabrica() as sesion:
        resultados = ingestar_manifiesto(
            sesion, c.recuperador, cargar_manifiesto(args.manifiesto), _admin(sesion).id,
            c.config, reindexar=args.reindexar,
        )
        for documento, n in resultados:
            print(f"  [{documento.estado}] {documento.titulo} v{documento.version}: {n} fragmentos")


def cmd_ejemplo(args) -> None:
    from syllabusai.ejemplo import CATALOGO, MANIFIESTO, generar_documentos
    from syllabusai.ingest.catalogo import importar_catalogo
    from syllabusai.ingest.pipeline import cargar_manifiesto, ingestar_manifiesto
    from syllabusai.seguridad import crear_usuario

    print("Generando documentos de EJEMPLO (perfil, malla, lineamientos de IA y sílabo aprobado, ficticios)...")
    generar_documentos()
    c = _contenedor(args)
    with c.fabrica() as sesion:
        usuarios = [("Administración del corpus", "admin@uti.ejemplo", "admin123", Rol.ADMIN_CORPUS),
                    ("Docente de prueba", "docente@uti.ejemplo", "docente123", Rol.DOCENTE)]
        for nombre, correo, clave, rol in usuarios:
            if sesion.scalar(select(Usuario).where(Usuario.correo == correo)) is None:
                crear_usuario(sesion, nombre, correo, clave, rol)
        importar_catalogo(sesion, CATALOGO)
        sesion.commit()
        print("Ingestando el corpus (el Modelo Educativo puede tardar un minuto)...")
        for documento, n in ingestar_manifiesto(
            sesion, c.recuperador, cargar_manifiesto(MANIFIESTO), _admin(sesion).id, c.config,
            reindexar=args.reindexar,
        ):
            print(f"  [{documento.estado}] {documento.titulo}: {n} fragmentos")
    print("\nListo. Usuarios: admin@uti.ejemplo / admin123 · docente@uti.ejemplo / docente123")


def cmd_buscar(args) -> None:
    c = _contenedor(args)
    tipos = [TipoDocumento(t) for t in args.tipo] if args.tipo else None
    for r in c.recuperador.buscar(args.consulta, tipos=tipos, carrera=args.carrera, k=args.k):
        print(f"\n[{r.fragmento.fragmento_id}] {r.cita} · {' > '.join(r.fragmento.ruta_seccion)}")
        print(f"  puntaje={r.puntaje:.4f} léxico={r.puntaje_lexico:.4f}")
        print("  " + r.fragmento.texto[:300].replace("\n", " ") + ("…" if len(r.fragmento.texto) > 300 else ""))


def cmd_demo(args) -> None:
    c = _contenedor(args)
    with c.fabrica() as sesion:
        asignatura = sesion.scalar(select(Asignatura).where(Asignatura.codigo == args.asignatura))
        docente = sesion.scalar(select(Usuario).where(Usuario.rol == Rol.DOCENTE).order_by(Usuario.id))
        if asignatura is None or docente is None:
            sys.exit("Falta la asignatura o un docente: ejecute `syllabusai ejemplo` primero.")
        ids = asignatura.id, docente.id
    silabo_id = c.servicio.crear_silabo(ids[1], ids[0], args.periodo, {
        "semanas_periodo": 16,
        "contexto_problema": args.contexto,
        "fuentes_problema": "Datos de ejemplo para la demostración.",
        "escenario": "la Universidad Tecnológica Indoamérica, sede Quito",
    })
    print(f"Sílabo {silabo_id} creado. Modelo: {c.llm.nombre}")
    pausa = c.orquestador.iniciar(silabo_id)
    while pausa["tipo"] == "revision_seccion":
        estado = c.servicio.estado(silabo_id)
        seccion = next(s for s in estado["secciones"] if s["clave"] == pausa["clave"])
        abiertos = [h for h in estado["hallazgos"] if h["seccion"] == pausa["clave"] and not h["resuelto"]]
        print(f"  {seccion['titulo']}: {seccion['estado']}, {len(seccion['citas'])} cita(s), "
              f"{len(abiertos)} hallazgo(s)")
        for h in abiertos:
            print(f"     - [{h['severidad']}] {h['regla']}: {h['mensaje']}")
        if seccion["estado"] == "abstenida":
            print("  La sección se abstuvo; la demostración se detiene aquí.")
            return
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    if pausa["tipo"] == "correccion":
        print("Verificación con hallazgos bloqueantes:")
        for h in pausa["hallazgos"]:
            print(f"  - {h['regla']} ({h['seccion']}): {h['mensaje']}")
        return
    for formato in ("docx", "pdf"):
        print(f"Exportado: {c.servicio.exportar(silabo_id, formato)}")


def cmd_metricas(args) -> None:
    from syllabusai.telemetry.eventos import exportar, leer_metricas_vllm, registrar

    c = _contenedor(args)
    with c.fabrica() as sesion:
        if args.vllm:
            metricas = leer_metricas_vllm(c.config.telemetria.metricas_vllm)
            registrar(sesion, "metricas_vllm", payload=metricas)
            sesion.commit()
            print(metricas)
        csv, json = exportar(sesion, c.config.telemetria.directorio)
    print(f"Eventos exportados:\n  {csv}\n  {json}")


def cmd_evaluar(args) -> None:
    from syllabusai.evaluacion import SALIDA, evaluar

    salida = Path(args.salida) if args.salida else SALIDA
    r = evaluar(salida, cargar_config(args.config))
    ag, rec = r["agente"], r["recuperacion"]
    print(f"Recall@{rec['k']}: {rec['recall']:.3f} · MRR: {rec['mrr']:.3f}")
    print(f"Pedidos del docente cumplidos: {ag['cumplimiento_indicaciones']:.1%} · "
          f"casos adversos correctos: {ag['adversos_correctos']:.1%} · "
          f"sílabos exportados: {ag['exportados']}/{len(ag['piloto'])}")
    print(f"Informe: {salida / 'informe_evaluacion.md'}")


def cmd_api(args) -> None:
    import uvicorn

    uvicorn.run("syllabusai.api.app:app", host=args.host, port=args.port)


def cmd_web(args) -> None:
    import uvicorn

    print(f"SyllabusAI web en http://{args.host}:{args.port}  (Ctrl+C para detener)")
    uvicorn.run("syllabusai.web.servidor:app", host=args.host, port=args.port)


def cmd_mallas(args) -> None:
    from syllabusai.ingest.importar_mallas import importar_carpeta

    c = _contenedor(args)
    with c.fabrica() as sesion:
        admin_id = _admin(sesion).id
        resultados = importar_carpeta(sesion, c, admin_id, reextraer=args.reextraer)
        sesion.commit()
        resumen = [(m.nombre, m.carrera, len(m.asignaturas), m.documento_id, m.avisos, extraida)
                   for m, extraida in resultados]
    for nombre, carrera, n, documento_id, avisos, extraida in resumen:
        print(f"  [{carrera}] {nombre}: {n} asignaturas" + ("" if extraida else " (ya importada)"))
        for aviso in avisos:
            print(f"      aviso: {aviso}")
        if extraida is not None:
            c.noticias.malla_importada(nombre, carrera, n, documento_id, avisos, admin_id)
    print("Revise las fichas en la web (Administración › Mallas) antes de publicarlas.")


def cmd_reindexar(args) -> None:
    """Vuelve a procesar todos los documentos del corpus en la base vectorial configurada
    (necesario al cambiar de modelo de embeddings, p. ej. al pasar a BGE-M3 en NVIDIA)."""
    from syllabusai.db.modelos import Documento
    from syllabusai.ingest.pipeline import procesar_documento, sincronizar_vigencia

    c = _contenedor(args)
    with c.fabrica() as sesion:
        for documento in sesion.scalars(select(Documento).order_by(Documento.id)):
            n = procesar_documento(sesion, c.recuperador, documento, c.config)
            print(f"  [{documento.estado}] {documento.titulo}: {n} fragmentos")
        sincronizar_vigencia(sesion, c.recuperador)
        sesion.commit()


def cmd_admin(args) -> None:
    from syllabusai.seguridad import contrasena_temporal, crear_usuario, hash_contrasena

    c = _contenedor(args)
    clave = args.clave or contrasena_temporal()
    with c.fabrica() as sesion:
        usuario = sesion.scalar(select(Usuario).where(Usuario.correo == args.correo.strip().lower()))
        if usuario is None:
            crear_usuario(sesion, args.nombre, args.correo, clave, Rol.ADMIN_CORPUS)
            accion = "creada"
        else:
            usuario.rol, usuario.activo = Rol.ADMIN_CORPUS, True
            usuario.hash_contrasena = hash_contrasena(clave)
            accion = "restablecida"
        sesion.commit()
    print(f"Cuenta de administrador {accion}: {args.correo}")
    if not args.clave:
        print(f"Contraseña temporal: {clave}  (cámbiela en la web: menú de su cuenta)")


def cmd_ui(args) -> None:
    ruta = RAIZ / "syllabusai" / "ui" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ruta), "--server.port",
                    str(args.port), "--server.address", args.host], check=False)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="syllabusai", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="ruta a config.yaml (por defecto config/config.yaml)")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("init", help="crea la base y el administrador del corpus")
    p.add_argument("--nombre", default="Administración del corpus")
    p.add_argument("--correo", required=True)
    p.add_argument("--clave", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("usuario", help="crea un usuario")
    p.add_argument("--nombre", required=True)
    p.add_argument("--correo", required=True)
    p.add_argument("--clave", required=True)
    p.add_argument("--rol", choices=[r.value for r in Rol], default=Rol.DOCENTE.value)
    p.set_defaults(func=cmd_usuario)

    p = sub.add_parser("catalogo", help="importa la ficha curricular de las asignaturas")
    p.add_argument("ruta")
    p.set_defaults(func=cmd_catalogo)

    p = sub.add_parser("ingestar", help="procesa e indexa los documentos de un manifiesto")
    p.add_argument("manifiesto")
    p.add_argument("--reindexar", action="store_true")
    p.set_defaults(func=cmd_ingestar)

    p = sub.add_parser("ejemplo", help="prepara el corpus y los usuarios de ejemplo")
    p.add_argument("--reindexar", action="store_true")
    p.set_defaults(func=cmd_ejemplo)

    p = sub.add_parser("buscar", help="consulta directa al recuperador")
    p.add_argument("consulta")
    p.add_argument("--tipo", action="append", choices=[t.value for t in TipoDocumento])
    p.add_argument("--carrera")
    p.add_argument("--k", type=int, default=5)
    p.set_defaults(func=cmd_buscar)

    p = sub.add_parser("demo", help="genera, aprueba y exporta un sílabo completo")
    p.add_argument("--asignatura", default="ITI-501")
    p.add_argument("--periodo", default="B26")
    p.add_argument("--contexto", default=(
        "En la Universidad Tecnológica Indoamérica los docentes dedican varias horas a "
        "planificar asignaturas integrando documentos curriculares dispersos"
    ))
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("metricas", help="exporta los eventos registrados")
    p.add_argument("--vllm", action="store_true", help="lee también las métricas de vLLM (RF-53)")
    p.set_defaults(func=cmd_metricas)

    p = sub.add_parser("evaluar", help="ejecuta la evaluación completa (SPEC, sección 11)")
    p.add_argument("--salida", help="carpeta de resultados (por defecto eval/resultados)")
    p.set_defaults(func=cmd_evaluar)

    p = sub.add_parser("api", help="levanta la API FastAPI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_api)

    p = sub.add_parser("web", help="levanta la página web completa (API + interfaz + vigía)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("mallas", help="importa las mallas del CES de la carpeta MALLAS")
    p.add_argument("--reextraer", action="store_true", help="vuelve a extraer aunque ya estén")
    p.set_defaults(func=cmd_mallas)

    p = sub.add_parser("reindexar", help="reprocesa todo el corpus en la base vectorial configurada")
    p.set_defaults(func=cmd_reindexar)

    p = sub.add_parser("admin", help="crea o restablece una cuenta de administrador")
    p.add_argument("--correo", required=True)
    p.add_argument("--nombre", default="Administrador")
    p.add_argument("--clave", help="si se omite, se genera una contraseña temporal")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("ui", help="levanta la interfaz Streamlit")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8501)
    p.set_defaults(func=cmd_ui)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

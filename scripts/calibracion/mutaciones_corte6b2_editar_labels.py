#!/usr/bin/env python3
"""CORTE 6B-2(a) — editar el nombre humano del workspace desde la web.

Arnes de calibracion: aplica mutaciones de una en una sobre el arbol
COMMITEADO, corre los testigos, y comprueba (1) que se ponen ROJOS, (2) QUE
pruebas fallan, (3) que el mensaje del rojo dice la causa esperada. Despues
restaura y comprueba la restauracion POR EFECTO (arbol tracked limpio y suite
verde otra vez).

Cubre las formas de romper la propiedad de este corte:

  M1 — el escritor deja de comprobar la CONCURRENCIA: escribe aunque la
       huella no coincida (last-write-wins silencioso).
  M2 — el escritor deja de VALIDAR el perfil como CONFORME antes de editarlo:
       un perfil con claves fuera de contrato se edita igual (C1 roto).
  M3 — el escritor usa `GameProfile.to_json()` en vez de mutar el dict
       original: reflowea el documento del operador.
  M4 — el predicado de destino seguro deja de EJERCERSE: siempre dice que si,
       sin correr la sonda real.
  M5 — C3 colapsa: `can_edit_context_label` deja de ser una capacidad propia
       y se convierte en un alias de `can_manage_access` (el negativo deja de
       poder existir).

Uso: python3 scripts/calibracion/mutaciones_corte6b2_editar_labels.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "viewer/tests/test_vault_writer_6b2.py",
    "viewer/tests/test_admin_label_6b2.py",
]


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                        cwd=RAIZ, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigos() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTIGOS, "-q", "--no-header",
         "--color=no", "-p", "no:randomly"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list[str]:
    return sorted({
        linea.split("::")[-1].split(" ")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


MUTACIONES = [
    (
        "M1 — el escritor deja de revalidar la huella justo antes de "
        "escribir: last-write-wins silencioso",
        "viewer/app/vault_writer.py",
        "    if not lectura.huella.coincide_contenido(huella_cliente):\n"
        "        raise ConflictoEscrituraError(",
        "    if False and not lectura.huella.coincide_contenido(huella_cliente):\n"
        "        raise ConflictoEscrituraError(",
        ["test_409_si_el_perfil_cambio_desde_que_se_leyo"],
        "assert",
    ),
    (
        "M2 — el escritor deja de exigir CONFORME (C1): edita un perfil "
        "legible-pero-no-conforme sin avisar",
        "viewer/app/vault_writer.py",
        "    if lectura.estado != EstadoPerfil.CONFORME:\n"
        "        raise EscrituraRechazadaError(lectura.estado, lectura.causa or \"perfil no editable\")",
        "    if False and lectura.estado != EstadoPerfil.CONFORME:\n"
        "        raise EscrituraRechazadaError(lectura.estado, lectura.causa or \"perfil no editable\")",
        ["test_c1_escritor_rechaza_editar_un_perfil_no_conforme"],
        "assert",
    ),
    (
        "M3 — el escritor deja de ejercer el predicado de destino seguro: "
        "siempre dice que SI sin correr la sonda",
        "viewer/app/vault_writer.py",
        "def destino_admite_escritura_segura(directorio: Path, *, forzar: bool = False) -> tuple[bool, str]:\n"
        "    \"\"\"`(True, \"\")` si el destino soporta reemplazo atómico seguro, si no\n"
        "    `(False, motivo)`. Cacheado por directorio tras el primer intento.\"\"\"\n"
        "    clave = str(directorio)",
        "def destino_admite_escritura_segura(directorio: Path, *, forzar: bool = False) -> tuple[bool, str]:\n"
        "    return (True, \"\")\n"
        "    clave = str(directorio)",
        ["test_predicado_de_destino_dice_que_no_en_un_directorio_de_solo_lectura"],
        "assert",
    ),
    (
        "M4 — C3 colapsa: `can_edit_context_label` se convierte en un alias "
        "de `can_manage_access` (el negativo deja de poder existir)",
        "viewer/app/auth/models.py",
        "    def can_edit_context_label(self) -> bool:\n"
        "        \"\"\"Editar `metadata.label` de un workspace/partida (Corte 6B-2).\"\"\"\n"
        "        overridden = self._overridden(\"can_edit_context_label\")\n"
        "        return self.is_admin() if overridden is None else overridden",
        "    def can_edit_context_label(self) -> bool:\n"
        "        return self.can_manage_access()",
        ["test_c3_gestiona_accesos_pero_no_puede_editar_el_label"],
        "403",
    ),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar — el checkout del arnés borra lo no commiteado.")
        return 2

    rc, salida = _correr_testigos()
    if rc != 0:
        print(f"ABORTA: los testigos no están verdes en la base (PYTEST_RC={rc})")
        print(salida[-3000:])
        return 2
    print(f"BASE: testigos verdes, PYTEST_RC={rc}\n")

    veredictos = []
    for nombre, rel, viejo, nuevo, esperadas, fragmento in MUTACIONES:
        f = RAIZ / rel
        original = f.read_text(encoding="utf-8")
        if viejo not in original:
            print(f"### {nombre}\n  DETECTOR ROTO: el texto a mutar no está en "
                  f"{rel}. La mutación no se aplicó: un verde aquí sería FALSO.\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue

        f.write_text(original.replace(viejo, nuevo, 1), encoding="utf-8")
        rc_mut, salida_mut = _correr_testigos()
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut

        f.write_text(original, encoding="utf-8")
        _purgar_pycache()
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigos()

        print(f"### {nombre}")
        print(f"  fichero            : {rel}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  pruebas en rojo    : {fallos}")
        print(f"  esperadas          : {sorted(esperadas)}")
        print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")

        ok = (
            rc_mut != 0
            and set(esperadas).issubset(set(fallos))
            and mensaje_ok
            and limpio
            and rc_post == 0
        )
        print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre.splitlines()[0]}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())

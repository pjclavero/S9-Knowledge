# 10 · Clonar en el PC (Windows)

Ruta local deseada:

```
E:\Projectos Esp32\S9 Knowledge
```

## Requisitos

- Git para Windows instalado.
- Acceso al repositorio remoto (clave SSH o credenciales HTTPS configuradas).

## Clonado (PowerShell)

```powershell
cd "E:\Projectos Esp32"
git clone <URL_DEL_REPO> "S9 Knowledge"
cd "S9 Knowledge"
git status
```

Sustituye `<URL_DEL_REPO>` por la URL real (p.ej.
`git@github.com:USUARIO/s9-knowledge.git` o la HTTPS equivalente).

## Tras clonar

```powershell
Copy-Item .env.example .env
# editar .env con los valores reales (no se sube al repo)
```

- El `.venv`, el estado de runtime y las bases de datos SQLite **no** vienen en el
  repo: se recrean localmente (ver `08-deployment-vm105.md`).
- El repo principal de trabajo será este del PC; el servidor VM105 conserva la
  instalación en producción.

## Nota sobre la ruta con espacios

La ruta contiene espacios ("S9 Knowledge", "Projectos Esp32"): entrecomilla siempre
las rutas en PowerShell, como en los ejemplos.

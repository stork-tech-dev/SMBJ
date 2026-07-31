#!/bin/sh
#
# Arranque del contenedor.
#
# Existe porque en un PaaS (Railway, Fly, Render) no hay un paso manual entre
# el deploy y el arranque: si las migraciones no corren acá, la aplicación
# levanta contra una base vacía y falla en la primera consulta.
#
# En desarrollo docker-compose sobreescribe el comando con --reload, así que
# este script solo corre en producción.

set -e

echo "==> Aplicando migraciones"
alembic upgrade head

# El seed es idempotente: cada INSERT está guardado por un WHERE NOT EXISTS,
# así que correrlo en cada deploy no pisa datos. Es lo que garantiza que
# existan los roles, la configuración y el usuario inicial: sin esto, un
# despliegue nuevo no tendría con qué iniciar sesión.
if [ -n "$DATABASE_URL" ]; then
    echo "==> Aplicando seed (idempotente)"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/seed.sql
else
    echo "==> Sin DATABASE_URL: se omite el seed"
fi

# ${PORT} lo inyecta la plataforma y hay que escucharlo, o el tráfico nunca
# llega: el contenedor queda "activo" y la URL da error.
PUERTO="${PORT:-8000}"
echo "==> Iniciando uvicorn en el puerto ${PUERTO}"

# exec para que uvicorn sea el PID 1 y reciba las señales de la plataforma:
# sin esto, un SIGTERM de un redeploy no cierra las conexiones ordenadamente.
exec uvicorn main:app --host 0.0.0.0 --port "${PUERTO}"

# Construir desde la raíz del proyecto:  docker build -f deploy/Dockerfile -t railguard .
FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN useradd -r rg && mkdir -p /app/data
# Descarga el trazado oficial al construir la imagen: el servicio arranca con el mapa ya listo y la versión anterior
# sigue sirviendo mientras tanto. Si la fuente no responde, el build continúa y el servidor lo reintenta al arrancar.
# (la descarga del trazado se hace en segundo plano al arrancar: hacerla en el build tardaba ~20 min por despliegue)
RUN chown -R rg /app/data
USER rg
EXPOSE 8080
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8080"]

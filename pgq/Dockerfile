FROM educationwarehouse/edwhale-3.14:latest

COPY requirements.txt /home/microservices
RUN uv pip install -r /home/microservices/requirements.txt

USER microservices

# CMD see docker compose

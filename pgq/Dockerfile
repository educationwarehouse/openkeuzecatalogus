FROM educationwarehouse/edwhale-3.14:latest

COPY requirements.txt /home/microservices
RUN uv pip install --no-cache -r /home/microservices/requirements.txt
COPY heartbeat.sh /opt/heartbeat.sh
RUN chmod +x /opt/heartbeat.sh

USER microservices

# CMD see docker compose

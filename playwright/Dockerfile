FROM educationwarehouse/edwhale-3.14:latest

COPY requirements.txt /home/microservices
RUN uv pip install --no-cache -r /home/microservices/requirements.txt

RUN playwright install-deps chromium

USER microservices

RUN playwright install chromium

# CMD see docker compose

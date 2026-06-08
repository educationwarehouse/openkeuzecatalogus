FROM educationwarehouse/edwhale-3.14:latest

COPY requirements.txt /home/microservices
RUN uv pip install -r /home/microservices/requirements.txt

RUN playwright install --with-deps

USER microservices

RUN playwright install chromium

# CMD see docker compose

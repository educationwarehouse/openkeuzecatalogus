FROM educationwarehouse/edwhale-3.14:latest

COPY requirements.txt .
RUN uv pip install -r requirements.txt

USER microservices

# CMD see docker-compose.yml

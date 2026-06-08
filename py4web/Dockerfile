FROM educationwarehouse/edwhale-3.14:latest

# Generate Dutch locale
RUN apt-get update && \
    apt-get install -y --no-install-recommends locales && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# locale-gen nl_NL doesn't seem to work but this does:
RUN echo "nl_NL ISO-8859-1" >> /etc/locale.gen && \
    echo "nl_NL.UTF-8 UTF-8" >> /etc/locale.gen && \
    locale-gen && update-locale && \
    dpkg-reconfigure locales

WORKDIR  /p4w
# expose py4web on its default port
EXPOSE 8000
EXPOSE 7999

COPY requirements.txt /p4w/requirements.txt
RUN uv pip install --upgrade --no-cache -r /p4w/requirements.txt

USER microservices
ENV PATH=/home/microservices/.local/bin:$PATH

# CMD see docker compose

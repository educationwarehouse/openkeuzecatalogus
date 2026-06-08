FROM educationwarehouse/edwhale-3.14:latest

COPY requirements.txt .
RUN uv pip install -r requirements.txt

USER microservices
# install as the microservices user, and authenticate accordingliy
RUN uvenv install b2
ARG B2_ATTACHMENTS_KEYID
ARG B2_ATTACHMENTS_KEY
RUN if [ "${B2_ATTACHMENTS_KEYID}" ]; then ~/.local/bin/b2 authorize-account ${B2_ATTACHMENTS_KEYID} ${B2_ATTACHMENTS_KEY}; fi;

# CMD see docker-compose.yml

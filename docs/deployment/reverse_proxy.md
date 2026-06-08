This repo uses a reverse proxy, for which we use Traefik. 

This repo considers using the following traefik repository:
https://github.com/educationwarehouse/reverse_proxy

When using this repo, there are some requirements, traefik uses a broker network to communicate with other containers and uses labels to declare behaviour.


The broker network is declared as following: 

```
networks:
  broker:
    name: broker
    external: true
```
In the service under the network section it should be declared aswell:

```
  service:
    networks:
      - broker
```

Traefik also uses labels to discover and see settings for docker services, these need to be configured in the following way:

```
  service:
    labels:
      - "traefik.enable=true"
      - "traefik.http.services.${PROJECT}-py4web-dev.loadbalancer.server.port=8000"
      - "traefik.http.routers.${PROJECT}-fragments-secure.tls=true"
      - "traefik.http.routers.${PROJECT}-fragments-secure.tls.certresolver=${CERTRESOLVER}"
      - "traefik.http.routers.${PROJECT}-fragments-secure.rule=Host(`fragments.${HOSTINGDOMAIN}`)"
      - "traefik.http.routers.${PROJECT}-fragments-secure.middlewares=strip-front-end-version, cors, www-redirect, edwh-std-security, regio-headers"
      - "traefik.http.routers.${PROJECT}-py4web-secure.tls=true"
      - "traefik.http.routers.${PROJECT}-py4web-secure.tls.certresolver=${CERTRESOLVER}"
      - "traefik.http.routers.${PROJECT}-py4web-secure.rule=Host(`${PY4WEB_SUBDOMAIN}.${HOSTINGDOMAIN}`) || Host(`www.${PY4WEB_SUBDOMAIN}.${HOSTINGDOMAIN}`) || Host(`${HOSTINGDOMAIN}`)"
      - "traefik.http.routers.${PROJECT}-py4web-secure.middlewares=cors, www-redirect, edwh-std-security, regio-headers"
```

The labels give the following functionality, first it enables traefik and sets a loadbalancer port. It then enables tls, to make traffic secure, and set up a certresolver (in our case this will be Letsencrypt).
It adds the domain which needs to be routed to the app and finally adds any corresponding middlewares. With the labels you can set up different apps simultanelessly with different behaviour, as seen by the fragments and py4web declarations.

The middlewares can either provide security and/or behaviour (like tls upgrade, www redirects, etc) and are either traefik standard or can be found within the traefik.yml in the revere_proxy repo.

Setting up traefik yourself can done using the readme from the reverse_proxy repo. 

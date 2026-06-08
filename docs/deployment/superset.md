Superset connects using the database connection variables located in the .env

To do this you either need to connect superset via an open port (managed by firewall or docker).

In our case we have hosted superset on another server and connect superset with it via an internal v-switch, since both our servers ar elocated in hetzner.
This allows superset to remotely read the database, without having to open any ports to the whole world. 

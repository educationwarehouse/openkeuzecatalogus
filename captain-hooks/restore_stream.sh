#!/bin/bash

restic $HOST -r $URI dump $SNAPSHOT --tag stream postgres.sql > ./migrate/data/database_to_restore.sql

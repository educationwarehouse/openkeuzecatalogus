#!/usr/bin/env bash
restic $HOST -r $URI backup --tag files --exclude sessions --exclude __pychache__ --exclude "*.bak" --exclude .shared.cache ./

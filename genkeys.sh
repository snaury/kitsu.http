#!/bin/sh
set -e
cd tests/certs
echo "::: Generating CA key :::"
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 1825 -subj '/O=kitsu.http/CN=kitsu.http.ca' -key ca.key -out ca.crt
echo "::: Generating server key :::"
openssl genrsa -out server.key 4096
openssl req -new -subj '/O=kitsu.http/CN=kitsu.http.server' -key server.key -out server.csr
echo "::: Signing server key :::"
openssl x509 -req -days 1825 -in server.csr -CA ca.crt -CAkey ca.key -set_serial 01 -out server.crt

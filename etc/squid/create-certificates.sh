CRT_DIR='/etc/squid/certificates'

sudo mkdir -p ${CRT_DIR}
sudo openssl req -x509 -sha256 -new -newkey rsa:4096 -keyout ${CRT_DIR}/ca.key -out ${CRT_DIR}/ca.crt -days 365 -nodes -subj '/O=Recipe Radar (development)'

kubectl create secret generic proxy-cert --from-file=${CRT_DIR}/ca.crt

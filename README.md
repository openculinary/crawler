# crawler

## Install dependencies

```
wget -qO - http://packages.diladele.com/diladele_pub.asc | sudo apt-key add -
echo 'deb [arch=amd64] http://squid48.diladele.com/ubuntu/ bionic main' | sudo tee /etc/apt/sources.list.d/squid48.diladele.com.list
sudo apt install \
  squid
sudo /usr/lib/squid/security_file_certgen -c -s /var/spool/squid/ssl_db -M 512MB
sudo cp etc/squid/recipe-radar.conf /etc/squid/conf.d/recipe-radar.conf
```

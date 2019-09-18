# crawler

## Install dependencies

```
wget -qO - http://packages.diladele.com/diladele_pub.asc | sudo apt-key add -
echo 'deb [arch=amd64] http://squid48.diladele.com/ubuntu/ bionic main' | sudo tee /etc/apt/sources.list.d/squid48.diladele.com.list
sudo apt install \
  squid
sudo cp etc/squid/recipe-radar.conf /etc/squid/conf.d/recipe-radar.conf
```

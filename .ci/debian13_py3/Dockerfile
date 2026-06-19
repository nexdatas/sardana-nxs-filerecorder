FROM debian:trixie

# MAINTAINER DESY, Jan Kotanski <jankotan@gmail.com>
# RUN /bin/bash -c 'echo "deb http://ftp.de.debian.org/debian trixie main" > /etc/apt/sources.list.d/debiande.list'
RUN apt-get -qq update && export DEBIAN_FRONTEND=noninteractive && apt-get purge curl wget
RUN apt-get -qq update && export DEBIAN_FRONTEND=noninteractive && apt-get -qq dist-upgrade
RUN apt-get install -y base-passwd
RUN apt-get -qq update  && apt-get -qq install -y libterm-readline-gnu-perl coreutils gnupg2 procps apt-utils curl apt-transport-https gnupg2 ca-certificates wget

RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections
RUN curl -4 https://ifconfig.co/ip
RUN curl -6 https://ifconfig.co/ip
RUN curl -v --retry 10 -s https://repos.pni-hdri.de/debian_repo.pub.gpg  | gpg --no-default-keyring --keyring gnupg-ring:/etc/apt/trusted.gpg.d/debian-hdri-repo.gpg --import
RUN chmod 644 /etc/apt/trusted.gpg.d/debian-hdri-repo.gpg

RUN cd /etc/apt/sources.list.d && wget https://repos.pni-hdri.de/trixie-pni-hdri.sources

RUN apt-get -qq update && apt-get -qq -y dist-upgrade
RUN apt-get -qq update && apt-get -qq install -y default-mysql-client  python3-h5py  python3-mysqldb python3-sphinx  apt-utils debconf-utils net-tools  omniidl libomniorb4-dev libcos4-dev libomnithread4-dev libzmq3-dev python3-pninexus python3-lxml python3-h5py python3-pninexus python3-pyqt5.qtsvg python3-qtchecker  qtchooser
RUN useradd -ms /bin/bash tango
RUN  /bin/bash -c 'export DEBIAN_FRONTEND=noninteractive; debconf-set-selections <<< "mysql-server mysql-server/root_password password rootpw"; debconf-set-selections <<< "mysql-server mysql-server/root_password_again password rootpw"; debconf-set-selections <<< "mariadb-server mysql-server/root_password password rootpw"; debconf-set-selections <<< "mariadb-server mysql-server/root_password_again password rootpw"; debconf-get-selections |grep mysql '
RUN apt-get -qq install -y default-mysql-server adduser
RUN  /bin/bash -c 'sleep 10'
RUN /bin/bash -c 'export DEBIAN_FRONTEND=noninteractive; debconf-set-selections <<< "tango-db tango-db/db/app-user string tango"; debconf-set-selections <<< "tango-db tango-db/mysql/app-pass	password rootpw"; debconf-set-selections <<< "tango-db tango-db/mysql/admin-pass password rootpw"; debconf-set-selections <<< "tango-db tango-db/password-confirm password rootpw"; debconf-set-selections <<< "tango-db tango-db/app-password-confirm password rootpw"; debconf-set-selections <<< "nxsconfigserver-db nxsconfigserver-db/mysql/app-pass password rootpw"; debconf-set-selections <<< "nxsconfigserver-db nxsconfigserver-db/mysql/admin-pass password rootpw"; debconf-set-selections <<< "nxsconfigserver-db nxsconfigserver-db/app-password-confirm password rootpw"; debconf-set-selections <<< "nxsconfigserver-db nxsconfigserver-db/db/app-user string tango"' \
     && sed -i "s/\[mysql\]/\[mysqld\]\nsql_mode = NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION\ncharacter-set-collations = latin1=latin1_swedish_ci\ncharacter-set-server=latin1\n\[mysql\]/g" /etc/mysql/conf.d/mysql.cnf


ENV HDF5_PLUGIN_PATH=/usr/lib/x86_64-linux-gnu/hdf5/plugins
ENV PKG_CONFIG_PATH=/home/tango/lib/pkgconfig
ENV DISPLAY=":99.0"
USER tango
WORKDIR /home/tango

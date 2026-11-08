#docker build . -t docker-samsungframe:latest
FROM fedora:37

RUN dnf update -y 
RUN dnf install -y dnf-plugins-core
RUN dnf install -y python2
RUN dnf install -y openssl
RUN dnf install -y libjpeg libpng fontconfig libX11 libXext libXrender xorg-x11-fonts-75dpi xorg-x11-fonts-Type1
RUN dnf install -y libusb 
#RUN dnf remove -y python-usb

COPY samsung-photo-frame-ctrl-master/ /samsung/
COPY wkhtmltox-0.12.6.1-2.almalinux9.x86_64.rpm .
RUN rpm -ivh wkhtmltox-0.12.6.1-2.almalinux9.x86_64.rpm

RUN python2 -m ensurepip --no-default-pip
RUN pip2 --version
RUN python2 -m pip install wheel
RUN python2 -m pip install pyusb

#RUN pip install pyusb==1.0.0b2 
#RUN chmod +x /QSUSB_linux/QSUSB/qsusb64

#RUN ls -l /QSUSB_linux/
#RUN ls -l /QSUSB_linux/QSUSB/

#RUN pip show pyusb
#RUN python2 --version

ADD entrypoint.sh /usr/bin/entrypoint.sh
RUN chmod +x /usr/bin/entrypoint.sh
ENTRYPOINT ["/usr/bin/entrypoint.sh"]

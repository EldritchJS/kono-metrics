FROM radanalyticsio/openshift-spark

USER root

ADD . /opt/kono

WORKDIR /opt/kono

RUN yum install -y python-pip \
 && pip install -r requirements.txt

USER 185

CMD ./run.sh

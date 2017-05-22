# export PYSPARK_PYTHON=python3

# spark likes to be able to lookup a username for the running UID, if
# no name is present fake it.
cat /etc/passwd > /tmp/passwd
echo "$(id -u):x:$(id -u):$(id -g):dynamic uid:$SPARK_HOME:/bin/false" >> /tmp/passwd

export NSS_WRAPPER_PASSWD=/tmp/passwd
# NSS_WRAPPER_GROUP must be set for NSS_WRAPPER_PASSWD to be used
export NSS_WRAPPER_GROUP=/etc/group

export LD_PRELOAD=libnss_wrapper.so

if [ -z $KONO_POSTGRES_URL ]; then
    echo "KONO_POSTGRES_URL not provided"
    exit 1
fi

if [ -z $KONO_SPARK_MASTER_URL ]; then
    echo "KONO_SPARK_MASTER_URL not provided"
    exit 1
fi

export OPH_DBURL=$KONO_POSTGRES_URL
export OPH_MASTER=$KONO_SPARK_MASTER_URL

exec spark-submit --master $OPH_MASTER --py-files worker.py ./app.py

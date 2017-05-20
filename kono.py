import sys
import os
import re
import json
import datetime as dt
import numpy as np
import pandas as pd
import requests
import psycopg2
from pyspark.sql import SparkSession
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from pyspark.sql import Row

def getRepoID(repoFullName):
    repoAPIURL = 'https://api.github.com/repos/' + repoFullName
    return requests.get(repoAPIURL).json()['id']

def checkIfInit(dbCur):
    query = '''SELECT EXISTS(
                SELECT * FROM information_schema.tables
                WHERE table_name=\'REPO_METRICS\');'''
    dbCur.execute(query)
    return cur.fetchone()[0]

def initDB(dbCur):
    query = '''CREATE TABLE REPO_METRICS(
                ID INT PRIMARY KEY NOT NULL,
                JSON_METRICS TEXT NOT NULL);'''
    dbCur.execute(query)

def checkIfCached(dbCur,rID):
    query = '''SELECT COUNT(ID)
                FROM REPO_METRICS
                WHERE ID=''' + str(rID) + ';'
    dbCur.execute(query)
    return (dbCur.fetchone()[0]==1)

def cacheRecord(dbCur,rID,metrics):
    query = '''INSERT INTO REPO_METRICS (ID, JSON_METRICS)
                VALUES(''' + str(rID) + ',\'' + metrics + '\');'
    dbCur.execute(query)


def parseGitHubUTCTimeStamp(ts):
    return dt.datetime.strptime(ts, '%Y-%m-%dT%H:%M:SZ')

def determineResolutionTime(opened,closed):
    td = closed - opened
    return abs(td.days)

def parseIssuesRecord(record):
    timeStamp = parseGitHubUTCTimeStamp(record['created_at'])
    issueID = record['payload']['issue']['id']
    action = record['payload']['action']
    return [issueID, [action, timeStamp]]

def parsePullRequestRecord(record):
    timeStamp = parseGitHubUTCTimeStamp(record['created_at'])
    pullRequestID = record['payload']['pull_reuest']['id']
    action = record['payload']['action']
    merged = record['payload']['pull_request']['merged']
    return [pullRequestID, [action, timeStamp, merged]]


def determineSentiments(messages, mType):
    analyzer = SentimentIntensityAnalyzer()
    neg=0
    pos=0
    neu=0
    numMessages=0

    for m in messages:
        numMessages+=1
        scores=analyzer.polarity_scores(m)
        neg+=scores['neg']
        pos+=scores['pos']
        neu+=scores['neu']

        if(numMessages > 0):
            neg/=numMessages
            pos/=numMessages
            neu/=numMessages
            total = neg+pos+neu
            neg = neg*100/total
            pos = pos*100/total
            neu = neu*100/total

        sentiments = [{'MessageType' : mType, 'SentimentType': 'Positive', 'Value': pos},\
                    {'MessageType' : mType, 'SentimentType': 'Neutral', 'Value': neu},\
                    {'MessageType' : mType, 'SentimentType': 'Negative', 'Value': neg}]

        return sentiments

def computeMetrics(sc,repoID):
    eventRecords = sc.textFile(inFiles)\
            .map(lambda record: record['repo']['id'] == rID)\
            .cache()

    eventCounts = eventRecords.map(lambda record: (record['type'],1))\
            .reduceByKey(lambda a, b: a+b)\
            .collect()

    issuesRecords = eventRecords\
            .filter(lambda record: record['type'] == 'IssuesEvent')

    openedRecords = issuesRecords\
            .filter(lambda record: record['payload']['action'] == 'opened')\
            .count()

    timesToCloseIssues = issuesRecords\
            .filter(lambda record: record['payload']['action'] == 'opened' or record['payload']['action'] == 'closed')\
            .map(lambda issuesRecord: parseIssuesRecord(issuesRecord))\
            .reduceByKey(lambda a,b: a+b)\
            .filter(lambda rec: len(rec[1])>2)\
            .map(lambda rec: determineResolutionTime(rec[1][1],rec[1][3]))\
            .collect()

    pullRequests = eventRecords\
            .filter(lambda record: record['type'] == 'PullRequestEvent')

    openedPullRequests = pullRequests\
            .filter(lambda record: record['payload']['action'] == 'opened')\
            .count()

    timesToClosePulls = pullRequests\
            .filter(lambda record: record['payload']['action'] == 'opened' or record['payload']['action'] == 'closed')\
            .map(lambda record: parsePullRequestRecord(record))\
            .reduceByKey(lambda a,b: a+b)\
            .filter(lambda rec: len(rec[1])>3)\
            .map(lambda rec: determineResolutionTime(rec[1][1],rec[1][4]))\
            .collect()

    commitMessages = eventRecords\
            .filter(lambda record: record['type'] == 'PushEvent')\
            .flatMap(lambda record: record['payload']['commits'])\
            .map(lambda record: record['message'])\
            .collect()

    commitMessageSentiments = determineSentiments(commitMessages,'Commit')

    issueCommentBodies = eventRecords\
            .filter(lambda record: record['type'] == 'IssueCommentEvent')\
            .map(lambda record: record['payload']['comment']['body'])\
            .collect()

    issueMessageSentiments = determineSentiments(issueCommentBodies, 'Issue')

    pullRequestReviewCommentRecords = eventRecords\
            .filter(lambda record: record['type'] == 'PullRequestReviewCommentEvent')\
            .map(lambda record: record['payload']['comment']['body'])\
            .collect()

    pullRequestMessageSentiments = determineSentiments(pullRequestReviewCommentRecords, 'PullRequest')

    return 'Computed'

spark = SparkSession\
        .builder\
        .config("spark.executor.heartbeatInterval","3600s")\
        .appName("kono")\
        .getOrCreate()

sc = spark.sparkContext
repoURL = 'https://github.com/radanalyticsio/oshinko-s2i'
repoFullName = repoURL.split('github.com/')[-1]
repoID = getRepoID(repoFullName)

conn = psycopg2.connect(dbname=dbName,user=dbUser,password=dbPassword,host=dbHost)
cur = conn.cursor()

if not checkIfInit(cur):
    initTable(cur)
    
cached = checkIfCached(cur, repoID)

if(cached):
    print repoID,' is Cached with values ',metrics
  
else:
    metrics=computeMetrics(sc,repoID)
    cacheRecord(cur,repoID,metrics)


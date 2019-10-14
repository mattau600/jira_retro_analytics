from flask import Flask
from flask import request, render_template
from decimal import *

import xml.etree.ElementTree as ET
import base64
from datetime import datetime, timedelta
import re
import requests

import sys
reload(sys)
sys.setdefaultencoding('utf-8')


# This script reports statistics for Epics from Jira
app = Flask(__name__)
HOURS_IN_DAY = 6


@app.route('/epic/', methods=['GET', 'POST'])
def serve_epic():
    if request.method == 'POST':
        try:            
            start_date = request.form['start']
            end_date = request.form['end']
            project_name = request.form['project_name']
            total_points, developers, testers, epics, errors = analyze_epic(project_name, start_date, end_date)
            return render_template('epic_analysis.html', project_name=project_name, start_date=start_date, end_date=end_date, total_points=total_points, developers=developers, testers=testers, epics=epics, errors=errors)
        except Exception:
            import traceback
            return traceback.format_exc()
    else:
        return render_template('epic_analysis.html')


def analyze_epic(project_name, start_date, end_date):

    re.sub(r'\W+', '', project_name)  # sanitize the project_name
    project_name = project_name.upper()

    total_points = 0
    developers = {}
    testers = {}
    epics = []
    errors = []
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Basic ' + base64.b64encode('Gitlab:hFVdWwxyX55v')
    }

    jira_url = "https://jira.sidechef.cn/rest/api/2/search?maxResults=500&jql=project%20%3D%20" + project_name + "%20and%20type%3Depic%20and%20created%20>%20%27" + start_date + "%27%20and%20created%20<%20%27" + end_date + "%27%20and%20cf%5B10003%5D%3DDone"
    response = requests.get(jira_url, headers=headers)

    if response.status_code == 200:
        response_json = response.json()
        if 'issues' in response_json:
            issues = response_json['issues']
            for issue in issues:
                epic_key = issue['key']
                epic_name = issue['fields']['summary']
                epic_points = 0
                if issue['fields']['customfield_10206']:
                    epic_points = issue['fields']['customfield_10206']
                epic_created = issue['fields']['created']
                epic_updated = issue['fields']['updated']                
                epic_total_dev_hours = 0.0
                epic_total_qa_hours = 0.0                
                epic_devs = {}
                epic_reviewers = {}
                epic_qas = {}
                task_entries = []
                
                epic_url = "https://jira.sidechef.cn/rest/api/2/search?jql=project%20%3D%20" + project_name + "%20and%20\"Epic%20Link\"%20%3D%20" + epic_key
                epic_response = requests.get(epic_url, headers=headers)
                if epic_response.status_code == 200:
                    epic_response_json = epic_response.json()
                    if 'issues' in epic_response_json:
                        epic_issues = epic_response_json['issues']
                        for task in epic_issues:
                            task_key = task["key"]                            
                            task_name = task["fields"]["summary"]
                            task_developer = task["fields"]["assignee"]["displayName"]
                            
                            # only consider epics that are Done, which uses a custom field oddly
                            #if task["fields"]["customfield_10003"] and task["fields"]["customfield_10003"]["value"] != "Done":
                            #    continue

                            if task["fields"]["customfield_10200"]:
                                task_reviewer = task["fields"]["customfield_10200"]["displayName"]
                            else:
                                task_reviewer = None
                                
                            if task["fields"]["customfield_10204"]:
                                task_qa_time_spent = task["fields"]["customfield_10204"]
                            else:
                                task_qa_time_spent = 0

                            epic_total_qa_hours += task_qa_time_spent

                            if task["fields"]["customfield_10201"]:
                                task_tester = task["fields"]["customfield_10201"]["displayName"]
                            else:
                                if task_qa_time_spent > 0: # no Tester, with hours in QA spent, so this is a QA task, we take the assignee
                                    task_tester = task["fields"]["assignee"]["displayName"]
                                else:
                                    task_tester = None

                            task_dev_time_spent = 0
                            if task["fields"]["timespent"]:
                                task_dev_time_spent = float(task["fields"]["timespent"]) / 3600

                            epic_total_dev_hours += task_dev_time_spent

                            if task_dev_time_spent > 0:
                                if task_developer in epic_devs:
                                    epic_devs[task_developer]['hours'] += task_dev_time_spent
                                else:
                                    epic_devs[task_developer] = {'hours': task_dev_time_spent}

                            if task_tester:
                                if task_tester in epic_qas:
                                    epic_qas[task_tester]['hours'] += task_qa_time_spent
                                else:
                                    epic_qas[task_tester] = {'hours': task_qa_time_spent}

                            if task_reviewer:
                                if task_reviewer in epic_reviewers:
                                    epic_reviewers[task_reviewer]['hours'] += task_dev_time_spent / 2
                                else:
                                    epic_reviewers[task_reviewer] = {'hours': task_dev_time_spent / 2}

                            print("key " + task_key)                            
                            task_entries.append({"key": task_key, "name": task_name.encode("utf-8"), "developer": task_developer, "tester": task_tester, "reviewer": task_reviewer, "dev_spent": task_dev_time_spent, "qa_spent": task_qa_time_spent})

                for dev in epic_devs:
                    epic_devs[dev]['points'] = epic_points / len(epic_devs)
                    if dev in developers:
                        developers[dev]["points"] += epic_points / len(epic_devs)
                    else:
                        developers[dev] = {"points": epic_points / len(epic_devs)}

                for qa in epic_qas:
                    epic_qas[qa]['points'] = epic_points / len(epic_qas)
                    if qa in testers:
                        testers[qa]["points"] += epic_points / len(epic_qas)
                    else:
                        testers[qa] = {"points": epic_points / len(epic_qas)}
                epic_total_hours = epic_total_dev_hours + epic_total_qa_hours

                epic = {"key": epic_key, "name": epic_name, "points": epic_points, "created": epic_created, "ended": epic_updated, 
                        "total_hours": epic_total_hours, "dev_hours": epic_total_dev_hours, "qa_hours": epic_total_qa_hours, "devs": epic_devs,
                        "reviewers": epic_reviewers, "qas": epic_qas, "tasks": task_entries}

                epics.append(epic)

                total_points += epic_points

    return total_points, developers, testers, epics, errors

if __name__ == '__main__':
    app.run(debug=True)

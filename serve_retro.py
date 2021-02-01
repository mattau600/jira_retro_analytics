from flask import Flask
from flask import request, render_template
from decimal import *

from datetime import datetime, timedelta
import re
import requests

import sys
import importlib
importlib.reload(sys)
# sys.setdefaultencoding('utf-8')

# This script takes xml generated by Jira for a single sprint, and then reports statistics for the sprint
app = Flask(__name__)
HOURS_IN_DAY = 6


@app.route('/', methods=['GET', 'POST'])
@app.route('/retro/', methods=['GET', 'POST'])  # legacy
def serve():
    if request.method == 'POST':
        try:
            sprint_id = int(request.form['sprint_id'])
            view_id = int(request.form['rapid_id'])
            sprint_name, start_date, end_date, total_working_hours, data, unplanned, deferred, misestimated, done_but_time_left, no_deferral_assignee, testers, total_qa_spent, total_tests = analyze_issue(sprint_id, view_id)

            return render_template('serve_retro.html', sprint_name=sprint_name, start_date=start_date, end_date=end_date, total_working_hours=total_working_hours,
                                   data=data, unplanned=unplanned, deferred=deferred, misestimated=misestimated, done_but_time_left=done_but_time_left,
                                   no_deferral_assignee=no_deferral_assignee, testers=testers, total_qa_spent=total_qa_spent, total_tests=total_tests)

        except Exception:
            import traceback
            return traceback.format_exc()
    else:
        return render_template("serve_retro.html")


def convert_to_time(time):
    if not time:
        return '0h'
    positive = True
    if time < 0:
        positive = False
    time = abs(time)
    from math import floor
    hours = floor(time)
    minutes = floor(time * 60 % 60)

    if hours and minutes:
        result = str(int(hours)) + 'h' + ' ' + str(int(minutes)) + 'm'
    elif hours:
        result = str(int(hours)) + 'h'
    else:
        result = str(int(minutes)) + 'm'
    return result if positive else "-" + result


def get_hours_spent_from_worklog(worklogs, start, end):
    time = 0
    if worklogs and 'worklogs' in worklogs:
        for worklog in worklogs['worklogs']:
            worklog_time = datetime.strptime(worklog['created'], "%Y-%m-%dT%H:%M:%S.000+0800")
            if worklog_time > start and worklog_time < end:
                time += worklog["timeSpentSeconds"]
    return time


def analyze_issue(sprint_id, view_id):
    headers = {
        'Accept': 'application/json',
        'Authorization': 'Basic ' + ''
    }
    url = "https://jira.sidechef.cn/rest/greenhopper/latest/rapid/charts/sprintreport?rapidViewId=" + str(view_id) + "&sprintId=" + str(sprint_id)
    response = requests.request("GET", url, headers=headers)
    if response.status_code == 200:
        api_info = response.json()

        start_date = api_info['sprint']['startDate']
        end_date = api_info['sprint']['endDate']
        sprint_name = api_info['sprint']['name']
        start_time = datetime.strptime(api_info['sprint']['startDate'], "%d/%b/%y %I:%M %p")
        end_time = datetime.strptime(api_info['sprint']['endDate'], "%d/%b/%y %I:%M %p")

        daygenerator = (start_time + timedelta(x + 1) for x in range((end_time - start_time).days + 1))
        working_days = sum(1 for day in daygenerator if day.weekday() < 5) - 1  # do not include planning day
        total_working_hours = working_days * HOURS_IN_DAY

        completed_issues = [i["key"] for i in api_info['contents']['completedIssues']]
        deferred_issues = [i["key"] for i in api_info['contents']['issuesNotCompletedInCurrentSprint'] + api_info['contents']['puntedIssues']]
        issues = completed_issues + deferred_issues
        unplanned_issues_dict = api_info['contents']['issueKeysAddedDuringSprint']

        issues_url = "https://jira.sidechef.cn/rest/api/2/search?jql=issueKey%20in%20(" + ",".join(issues) + ")&maxResults=300&fields=key,summary,timespent,timeestimate,created,issuetype,assignee,status,timeoriginalestimate,updated,customfield_10204,customfield_10201,customfield_10205,worklog"
        response = requests.request("GET", issues_url, headers=headers)
        if response.status_code == 200:
            issue_json = response.json()

            retro = {}
            total_time_spent_in_sprint = 0
            total_time_estimate = 0
            total_time_left = 0
            total_time_estimate_done = 0
            total_time_spent_done = 0
            total_time_unplanned = 0
            total_time_spent_bug = 0
            unplanned = {}
            deferred = {}
            misestimated = {}

            done_but_time_left = []
            no_deferral_assignee = []

            testers = {}
            total_qa_spent = 0
            total_tests = 0

            for item in issue_json["issues"]:

                issue = item['key']
                assignee = item['fields']['assignee']['displayName']
                title = '[' + item['key'] + '] ' + item['fields']['summary']
                type = item['fields']['issuetype']['name']
                created_time = datetime.strptime(item['fields']['created'], "%Y-%m-%dT%H:%M:%S.000+0800")
                updated_time = datetime.strptime(item['fields']['updated'], "%Y-%m-%dT%H:%M:%S.000+0800")

                hours_spent = int(item['fields']['timespent'] or 0) / 3600
                hours_spent_in_sprint = get_hours_spent_from_worklog(item['fields']['worklog'], start_time, end_time) / 3600

                if item['fields']['status']['name'] == "Done":
                    time_estimate = int(item['fields']['timeoriginalestimate'] or 0)
                    hours_estimate = time_estimate / 3600
                    time_left = 0
                    done_with_hours_left = time_left / 3600
                    hours_left = 0
                else:  # not done yet, we are not using it to calculate estimation accuracy
                    time_estimate = hours_estimate = 0
                    time_left = int(item['fields']['timeestimate'] or 0)
                    done_with_hours_left = 0
                    hours_left = time_left / 3600

                if assignee in retro:
                    record = retro[assignee]
                else:
                    record = {"total_estimated": 0, "total_spent": 0, "total_left": 0, "total_estimated_done": 0, "total_spent_done": 0, "total_unplanned": 0, "total_spent_bug": 0, "total_spent_in_sprint": 0, "created": created_time}
                    retro[assignee] = record

                total_time_estimate += hours_estimate
                total_time_left += hours_left
                total_time_spent_in_sprint += hours_spent_in_sprint

                record["total_estimated"] += hours_estimate
                record["total_spent"] += hours_spent
                record["total_left"] += hours_left
                record["total_spent_in_sprint"] += hours_spent_in_sprint

                if type == "Bug":
                    total_time_spent_bug += hours_spent
                    record["total_spent_bug"] += hours_spent

                link = "https://jira.sidechef.cn/browse/" + issue
                type_url = item['fields']['issuetype']['iconUrl']

                # Unplanned tasks
                if issue in unplanned_issues_dict:
                    total_time_unplanned += hours_spent

                    unplanned_entry = {"title": title, "assignee": assignee, "hours_left": convert_to_time(hours_left), "hours_spent": convert_to_time(hours_spent), "hours_spent_in_sprint": convert_to_time(hours_spent_in_sprint), "link": link, "created": created_time, "icon": type_url}
                    if assignee in unplanned:
                        unplanned[assignee].append(unplanned_entry)
                    else:
                        unplanned[assignee] = [unplanned_entry]
                    record["total_unplanned"] += hours_spent

                if item['fields']['status']['name'] in ["Done", "QA", "Code Review"]:
                    total_time_estimate_done += hours_estimate
                    total_time_spent_done += hours_spent
                    record["total_estimated_done"] += hours_estimate
                    record["total_spent_done"] += hours_spent
                    record["total_spent_in_sprint"] + hours_spent_in_sprint
                    if done_with_hours_left > 0:  # this is a strange case
                        done_but_time_left.append({"title": title, "assignee": assignee, "hours_left": convert_to_time(done_with_hours_left), "link": link})

                    if float(hours_estimate) > 0.1 and abs(float(hours_spent) - float(hours_estimate)) / float(hours_estimate) > .20:  # 60 seconds is used for QA.
                        misestimated_entry = {"title": title, "assignee": assignee, "hours_estimated": convert_to_time(hours_estimate), "hours_spent": convert_to_time(hours_spent), "over_by": convert_to_time(hours_spent - hours_estimate), "diff": int(round((hours_spent - hours_estimate) / hours_estimate, 2) * 100), "link": link, "created": created_time, "icon": type_url}
                        if assignee in misestimated:
                            misestimated[assignee].append(misestimated_entry)
                        else:
                            misestimated[assignee] = [misestimated_entry]

                elif issue in deferred_issues and hours_left > 0.1:  # tasks may be 'done', but remain in "issues not completed in sprint", greater than 60 seconds
                    deferred_entry = {"title": title, "assignee": assignee, "hours_left": convert_to_time(hours_left), "link": link, "icon": type_url, "updated": updated_time, "status": item['fields']['status']['name']}
                    if assignee in deferred:
                        deferred[assignee].append(deferred_entry)
                    else:
                        deferred[assignee] = [deferred_entry]

                qa_hours = 0
                qa_tests = 0
                tester = None

                if "customfield_10201" in item['fields'] and item['fields']['customfield_10201']:  # QA Tester
                    tester = item['fields']['customfield_10201']['displayName']
                if "customfield_10204" in item['fields'] and item['fields']['customfield_10204']:  # QA Hours
                    qa_hours = item['fields']['customfield_10204']
                if "customfield_10205" in item['fields'] and item['fields']['customfield_10205']:  # Automated tests
                    qa_tests = item['fields']['customfield_10205']

                if qa_hours or qa_tests:
                    if not tester:  # qa hours or qa tests exist, but no tester set, this is a QA test
                        tester = item['fields']['assignee']['displayName']

                    if tester in testers:
                        testers[tester]["total_qa_hours"] += qa_hours
                        testers[tester]["total_tests"] += qa_tests
                    else:
                        testers[tester] = {"total_qa_hours": qa_hours, "total_tests": qa_tests}
                    total_qa_spent += qa_hours
                    total_tests += qa_tests

            total_working_hours_team = total_working_hours * len(retro)
            data = []

            for assignee, record in retro.items():

                try:
                    data.append([assignee,
                                 convert_to_time(record["total_estimated"]),
                                 convert_to_time(record["total_estimated_done"]),
                                 convert_to_time(record["total_spent_done"]),
                                 convert_to_time(record["total_spent_in_sprint"]),
                                 convert_to_time(record["total_left"]),
                                 convert_to_time(record["total_unplanned"]),
                                 convert_to_time(record["total_spent_bug"]),
                                 int((record["total_spent_done"] / record["total_estimated_done"]) * 100),
                                 int((record["total_left"] / record["total_estimated"]) * 100),
                                 int((record["total_unplanned"] / record["total_estimated"]) * 100),
                                 int((record["total_spent_in_sprint"] / total_working_hours) * 100),
                                 int((record["total_spent_bug"] / record["total_spent_done"]) * 100)])

                    if Decimal(record["total_left"]) == 0:
                        no_deferral_assignee.append(assignee)

                except (ZeroDivisionError, InvalidOperation):
                    # we do not consider staff with 0 hours, as they are probably not team members
                    pass

            data.append(["Total",
                         convert_to_time(total_time_estimate),
                         convert_to_time(total_time_estimate_done),
                         convert_to_time(total_time_spent_done),
                         convert_to_time(total_time_spent_in_sprint),
                         convert_to_time(total_time_left),
                         convert_to_time(total_time_unplanned),
                         convert_to_time(total_time_spent_bug),
                         int((total_time_spent_done / total_time_estimate_done) * 100) if total_time_estimate_done else 0,
                         int((total_time_left / total_time_estimate) * 100) if total_time_estimate else 0,
                         int((total_time_unplanned / total_time_estimate) * 100) if total_time_estimate else 0,
                         int((total_time_spent_in_sprint / total_working_hours_team) * 100) if total_working_hours_team else 0,
                         int((total_time_spent_bug / total_time_spent_in_sprint) * 100) if total_time_spent_in_sprint else 0])

            return sprint_name, start_date, end_date, total_working_hours, data, unplanned, deferred, misestimated, done_but_time_left, no_deferral_assignee, testers, total_qa_spent, total_tests
        else:
            raise Exception("issues api request failed: " + url + " " + issues_url)
    else:
        raise Exception("api request failed: " + url)


@app.route('/epic/', methods=['GET', 'POST'])
def serve_epic():
    if request.method == 'POST':
        try:
            start_date = request.form['start']
            end_date = request.form['end']
            project_name = request.form['project_name']
            total_points, avg_lead_time, avg_efficiency, developers, testers, epics, errors = analyze_epic(project_name, start_date, end_date)
            return render_template('epic_analysis.html', project_name=project_name, start_date=start_date, end_date=end_date, total_points=total_points,
                                   avg_lead_time=avg_lead_time, avg_efficiency=avg_efficiency, developers=developers, testers=testers, epics=epics, errors=errors)
        except Exception:
            import traceback
            return traceback.format_exc()
    else:
        return render_template('epic_analysis.html')


def analyze_epic(project_name, start_date, end_date):

    re.sub(r'\W+', '', project_name)  # sanitize the project_name
    project_name = project_name.upper()

    total_points = 0
    total_lead_time = 0
    total_efficiency = 0
    developers = {}
    testers = {}
    epics = []
    errors = []
    headers = {
        'Accept': 'application/json',
        'Authorization': 'Basic ' + ''
    }

    jira_url = "https://jira.sidechef.cn/rest/api/2/search?maxResults=500&jql=project%20%3D%20" + project_name + "%20and%20type%3Depic%20and%20updated%20>%20%27" + start_date + "%27%20and%20updated%20<%20%27" + end_date + "%27%20and%20cf%5B10003%5D%3DDone"
    response = requests.request("GET", jira_url, headers=headers)

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
                epic_created = datetime.strptime(issue['fields']['created'][:10], "%Y-%m-%d")
                epic_ended = datetime.strptime(issue['fields']['updated'][:10], "%Y-%m-%d")

                epic_total_dev_hours = 0.0
                epic_total_qa_hours = 0.0
                epic_total_review_hours = 0.0
                epic_devs = {}
                epic_qas = {}
                task_entries = []

                epic_url = "https://jira.sidechef.cn/rest/api/2/search?jql=project%20%3D%20" + project_name + "%20and%20\"Epic%20Link\"%20%3D%20" + epic_key
                epic_response = requests.get(epic_url, headers=headers)
                if epic_response.status_code == 200:
                    epic_response_json = epic_response.json()

                    if 'issues' in epic_response_json:
                        epic_issues = epic_response_json['issues']
                        for task in epic_issues:

                            task_created = datetime.strptime(task["fields"]["created"][:10], "%Y-%m-%d")
                            if task_created < epic_created:
                                epic_created = task_created  # get the earliest task, in case epic created later
                            task_updated = datetime.strptime(task["fields"]["updated"][:10], "%Y-%m-%d")
                            if task_updated > epic_ended:
                                epic_ended = task_updated  # get the more recent date.  more recent is more greater

                            task_key = task["key"]
                            task_name = task["fields"]["summary"]
                            task_developer = task["fields"]["assignee"]["displayName"]

                            if task["fields"]["customfield_10200"]:
                                task_reviewer = task["fields"]["customfield_10200"]["displayName"]
                            else:
                                task_reviewer = None

                            if task["fields"]["customfield_10400"]:
                                task_review_time_spent = task["fields"]["customfield_10400"]
                            else:
                                task_review_time_spent = 0

                            epic_total_dev_hours += task_review_time_spent  # add review hours to total dev hours

                            if task["fields"]["customfield_10204"]:
                                task_qa_time_spent = task["fields"]["customfield_10204"]
                            else:
                                task_qa_time_spent = 0

                            epic_total_qa_hours += task_qa_time_spent

                            if task["fields"]["customfield_10201"]:
                                task_tester = task["fields"]["customfield_10201"]["displayName"]
                            else:
                                if task_qa_time_spent > 0:  # no Tester, with hours in QA spent, so this is a QA task, we take the assignee
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
                                    epic_devs[task_developer] = {'hours': task_dev_time_spent, 'review_hours': 0}

                            if task_tester:
                                if task_tester in epic_qas:
                                    epic_qas[task_tester]['hours'] += task_qa_time_spent
                                else:
                                    epic_qas[task_tester] = {'hours': task_qa_time_spent}

                            if task_reviewer and task_review_time_spent > 0:
                                if task_reviewer in epic_devs:
                                    epic_devs[task_reviewer]['review_hours'] += task_review_time_spent
                                else:
                                    epic_devs[task_reviewer] = {'hours': 0, 'review_hours': task_review_time_spent}

                            task_entries.append({"key": task_key, "name": task_name, "developer": task_developer, "tester": task_tester, "reviewer": task_reviewer, "dev_spent": task_dev_time_spent, "qa_spent": task_qa_time_spent, "review_spent": task_review_time_spent, "created": task_created, "last_updated": task_updated})

                lead_time = (epic_ended - epic_created).days

                for dev in epic_devs:
                    if epic_total_dev_hours > 0:
                        dev_contribution = (epic_devs[dev]['hours'] + epic_devs[dev]['review_hours']) / epic_total_dev_hours
                        epic_devs[dev]['points'] = epic_points * dev_contribution
                        if dev in developers:
                            developers[dev]["points"] += epic_points * dev_contribution
                        else:
                            developers[dev] = {"points": epic_points * dev_contribution}
                    else:
                        epic_devs[dev]['points'] = 0

                for qa in epic_qas:
                    if epic_total_qa_hours > 0:
                        qa_contribution = epic_qas[qa]['hours'] / epic_total_qa_hours
                        epic_qas[qa]['points'] = epic_points * qa_contribution
                        if qa in testers:
                            testers[qa]["points"] += epic_points * qa_contribution
                        else:
                            testers[qa] = {"points": epic_points * qa_contribution}
                    else:  # there are epics with no QA
                        epic_qas[qa]['points'] = 0
                epic_total_hours = epic_total_dev_hours + epic_total_qa_hours + epic_total_review_hours
                if epic_total_hours > 0:
                    efficiency = epic_points / epic_total_hours
                else:
                    efficiency = 0

                epic = {"key": epic_key, "name": epic_name, "points": epic_points, "created": epic_created, "ended": epic_ended,
                        "lead_time": lead_time,
                        "efficiency": efficiency,
                        "total_hours": epic_total_hours, "dev_hours": epic_total_dev_hours, "qa_hours": epic_total_qa_hours, "review_hours": epic_total_review_hours, "devs": epic_devs,
                        "qas": epic_qas, "tasks": task_entries}

                epics.append(epic)

                total_points += epic_points
                total_lead_time += lead_time
                total_efficiency += efficiency

    avg_lead_time = 0
    avg_efficiency = 0
    if len(epics) > 0:
        avg_lead_time = total_lead_time / len(epics)
        avg_efficiency = total_efficiency / len(epics)

    # sort the 2 dictionaries based on points
    developers = {k: v for k, v in sorted(developers.items(), key=lambda item: item[1]['points'], reverse=True)}
    testers = {k: v for k, v in sorted(testers.items(), key=lambda item: item[1]['points'], reverse=True)}

    return total_points, avg_lead_time, avg_efficiency, developers, testers, epics, errors


if __name__ == '__main__':
    app.run(debug=True)

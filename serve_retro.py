from flask import Flask
from flask import abort, request, render_template
from decimal import *

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# This script takes xml generated by Jira for a single sprint, and then reports statistics for the sprint
app = Flask(__name__)
HOURS_IN_DAY = 6


@app.route('/', methods=['GET', 'POST'])
@app.route('/retro/', methods=['GET', 'POST'])  # legacy
def serve():
    if request.method == 'POST':
        try:
            filename = request.files['xml_file']
            start_date = request.form['start']
            end_date = request.form['end']
            total_working_hours, data, unplanned, deferred, done_but_time_left = retro(filename, start_date, end_date)
            return render_template('serve_retro.html', start_date=start_date, end_date=end_date, total_working_hours=total_working_hours, data=data, unplanned=unplanned, deferred=deferred, done_but_time_left=done_but_time_left)
        except Exception:
            import traceback
            return traceback.format_exc()
    else:
        return render_template('serve_retro.html')


def convert_to_time(time):
    if not time:
        return '0h'
    from math import floor
    hours = floor(time)
    minutes = floor(time * 60 % 60)

    if hours and minutes:
        return str(int(hours)) + 'h' + ' ' + str(int(minutes)) + 'm'
    elif hours:
        return str(int(hours)) + 'h'
    else:
        str(int(minutes)) + 'm'


def retro(filename, start_date, end_date):

    tree = ET.parse(filename)
    root = tree.getroot()
    channel = root.find("channel")

    start_time = datetime.strptime(start_date, "%Y-%m-%d")
    end_time = datetime.strptime(end_date, "%Y-%m-%d")
    daygenerator = (start_time + timedelta(x + 1) for x in xrange((end_time - start_time).days + 1))
    working_days = sum(1 for day in daygenerator if day.weekday() < 5)

    total_working_hours = working_days * HOURS_IN_DAY

    retro = {}
    total_time_spent = 0
    total_time_estimate = 0
    total_time_left = 0
    total_time_estimate_done = 0
    total_time_spent_done = 0
    total_time_unplanned = 0
    total_time_spent_bug = 0
    unplanned = {}
    deferred = {}
    done_but_time_left = []

    for item in channel.findall('item'):
        assignee = item.find('assignee').text
        title = item.find('title').text

        time_estimate = item.find('timeoriginalestimate')

        if time_estimate is not None:
            hours_estimate = Decimal(time_estimate.get("seconds")) / 3600
        else:
            hours_estimate = 0

        time_left = item.find('timeestimate')
        if time_left is not None:
            hours_left = Decimal(time_left.get("seconds")) / 3600
        else:
            hours_left = 0

        time_spent = item.find('timespent')
        if time_spent is not None:
            hours_spent = Decimal(time_spent.get("seconds")) / 3600
        else:
            hours_spent = 0
            
        type = item.find('type').text
        
        created_time = datetime.strptime(item.find('created').text, "%a, %d %b %Y %H:%M:%S +0800")

        if assignee in retro:
            record = retro[assignee]
        else:
            record = {"total_estimated": 0, "total_spent": 0, "total_left": 0, "total_estimated_done": 0, "total_spent_done": 0, "total_unplanned": 0, "total_spent_bug":0 }
            retro[assignee] = record

        total_time_estimate += hours_estimate
        total_time_left += hours_left
        total_time_spent += hours_spent

        record["total_estimated"] += hours_estimate
        record["total_spent"] += hours_spent
        record["total_left"] += hours_left
        
        if type == "Bug":
            total_time_spent_bug += hours_spent
            record["total_spent_bug"] += hours_spent 

        time_diff = created_time - start_time

        link = item.find("link").text
        type_url = item.find("type").get("iconUrl")

        if time_diff > timedelta(days=1):  # created 1 day after start of sprint
            total_time_unplanned += hours_spent
            record["total_unplanned"] += hours_spent

            unplanned_entry = {"title": title, "assignee": assignee, "hours_left": convert_to_time(hours_left), "hours_spent": convert_to_time(hours_spent), "link": link, "created": item.find('created').text, "icon": type_url}
            if assignee in unplanned:
                unplanned[assignee].append(unplanned_entry)
            else:
                unplanned[assignee] = [unplanned_entry]

        if item.find("resolution").text == 'Done':
            total_time_estimate_done += hours_estimate
            total_time_spent_done += hours_spent
            record["total_estimated_done"] += hours_estimate
            record["total_spent_done"] += hours_spent
            if hours_left > 0:  # this is a strange case
                done_but_time_left.append({"title": title, "assignee": assignee, "hours_left": convert_to_time(hours_left), "link": link, "updated": item.find('updated').text})
        elif item.find("resolution").text == "Unresolved":
            deferred_entry = {"title": title, "assignee": assignee, "hours_left": convert_to_time(hours_left), "link": link, "updated": item.find('updated').text}
            if assignee in deferred:
                deferred[assignee].append(deferred_entry)
            else:
                deferred[assignee] = [deferred_entry]

    total_working_hours_team = total_working_hours * len(retro)

    data = []

    for assignee, record in retro.iteritems():

        try:
            data.append([assignee,
                         convert_to_time(record["total_estimated"]),
                         convert_to_time(record["total_estimated_done"]),
                         convert_to_time(record["total_spent_done"]),
                         convert_to_time(record["total_spent"]),
                         convert_to_time(record["total_left"]),
                         convert_to_time(record["total_unplanned"]),
                         convert_to_time(record["total_spent_bug"]),
                         int((Decimal(record["total_spent_done"]) / record["total_estimated_done"]) * 100),
                         int((Decimal(record["total_left"]) / record["total_estimated"]) * 100),
                         int((Decimal(record["total_unplanned"]) / record["total_estimated"]) * 100),
                         int((Decimal(record["total_spent"]) / total_working_hours) * 100),
                         int((Decimal(record["total_spent_bug"]) / record["total_spent_done"]) * 100)])
        except (ZeroDivisionError, InvalidOperation):
            data.append([assignee,
                         convert_to_time(record["total_estimated"]),
                         convert_to_time(record["total_estimated_done"]),
                         convert_to_time(record["total_spent_done"]),
                         convert_to_time(record["total_spent"]),
                         convert_to_time(record["total_left"]),
                         convert_to_time(record["total_unplanned"]),
                         convert_to_time(record["total_spent_bug"]),
                         '-',
                         '-',
                         '-',
                         '-',
                         '-'])
            pass

    data.append(["Total",
                 convert_to_time(total_time_estimate),
                 convert_to_time(total_time_estimate_done),
                 convert_to_time(total_time_spent_done),
                 convert_to_time(total_time_spent),
                 convert_to_time(total_time_left),
                 convert_to_time(total_time_unplanned),
                 convert_to_time(total_time_spent_bug),
                 int((Decimal(total_time_spent_done) / total_time_estimate_done) * 100),
                 int((Decimal(total_time_left) / total_time_estimate) * 100),
                 int((Decimal(total_time_unplanned) / total_time_estimate) * 100),
                 int((Decimal(total_time_spent) / total_working_hours_team) * 100),
                 int((Decimal(total_time_spent_bug) / total_time_spent) * 100)])
    return total_working_hours, data, unplanned, deferred, done_but_time_left


if __name__ == '__main__':
    app.run(debug=True)

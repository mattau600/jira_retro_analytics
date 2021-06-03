# Jira Agile Sprint Retrospective Analytics

A Python Flask app that supports analyzing the xml dumped from Jira Agile 7.x.  Requires sprint team to use hours to estimate instead of story points.

In "Sprint Report", you can "View sprint issues in Issue Navigator", and from there you can "Export" to XML.  This tool takes the XML file and produce the following analysis:

 - Estimation hours compared to time actually spent
 - % of sprint items deferred
 - % of sprint items are unplanned
 - % utilization of a team member, assuming a 6 hour workload per day
 - % time spent on bugs.

Also will list out the unplanned items and deferred items for discussion.

#!/usr/bin/env python3
import getpass
import re
import urllib
from collections import defaultdict
from datetime import datetime
from pprint import pprint

import requests
from bs4 import BeautifulSoup
from requests_toolbelt import MultipartEncoder


def getSoup(content):
    return BeautifulSoup(content, features="html.parser")


def fromPage(href=""):
    def decorator(func):
        def toReturn(self, *args, **kwargs):
            content = self._session.get(self._path + href).content
            soup = getSoup(content.decode())
            return func(self, soup, *args, **kwargs)

        return toReturn

    return decorator


def authenticityToken(soup):
    return soup.select_one("meta[name=csrf-token]")["content"]
    # I though that the csrf-token was always propagated to all authenticty
    # tokens. Apparently not and that cost me 3 days
    return soup.select_one("input[name=authenticity_token]")["value"]


def submitForm(href="", multipart=False):
    def decorator(func):
        @fromPage(href)
        def toReturn(self, soup, *args, **kwargs):
            data = func(self, *args, **kwargs)
            data["authenticity_token"] = authenticityToken(soup)
            headers = {}

            if multipart:
                data = MultipartEncoder(fields=data)
                headers["content-type"] = data.content_type

            response = self._session.post(
                self._path + href,
                headers=headers,
                allow_redirects=False,
                data=data
            )
            # Gradescope returns a 302 FOUND if the form was accepted
            # Requests are truthy if 200 <= status_code < 400
            return response if response.status_code == requests.codes.found else None

        return toReturn

    return decorator


def toGS(val):
    """
        Serializes value to format appropriate for Gradescope forms
    """
    converters = {
        datetime: lambda val: val.strftime("%b %d %Y %I:%M %p"),
        bool: lambda val: int(val),
    }

    return val if type(val) not in converters else converters[type(val)](val)


class GradescopeSession(requests.Session):
    BASE_URL = "https://www.gradescope.com/"

    def __init__(self, email=None, password=None, *args, **kwargs):
        super(GradescopeSession, self).__init__(*args, **kwargs)
        self._session = self  # To make the decorator simpler
        self._path = ""  # To make the decorator simpler

        if email is None or password is None:
            email = input("Gradescope user: ")
            password = getpass.getpass("Password: ")

        if not self.login(email, password):
            print("Error: Login failed, try again")
            exit()
        # while not self.login(email, password):
        #     print("Error: Login failed, try again")

    def request(self, method, url, *args, **kwargs):
        # Avoid needing to specify https://gradescope.com every time
        url = urllib.parse.urljoin(self.BASE_URL, url)
        return super(GradescopeSession,
                     self).request(method, url, *args, **kwargs)

    @submitForm("/login")
    def login(self, email, password):
        """
            Logs in. Returns a truthy value if successful
        """
        return {
            "session[email]": email,
            "session[password]": password,
        }

    @property
    @fromPage("/account")
    def classes(self, soup):
        """
        Edited by Chami Lamelas (slamel01)
        1/16/2023 

        Changes made to scrape Gradescope's new HTML format.
        Previous code did not properly identify courses.
        """

        # Builds list of Class - returned
        classes = list()

        # Current semester (see below)
        curr_sem = None

        # .pageHeading h1 elements are Instructor Courses, Student Courses, etc.
        # hence these are used to identify the roles the current user has in
        # said courses
        for role in soup.select(".pageHeading"):

            # move from .pageHeading to next div at same hierarchical level (i.e. sibling)
            # that is courseList - courses seem to sit in here - e stands for course list 
            # element
            for e in role.find_next_sibling("div", class_="courseList"):

                # Some of the divs under courseList are the term of the course, we extract
                # the text of the div which will be like "Fall 2022" and set that as the 
                # current semester
                if e['class'][0] == 'courseList--term':
                     curr_sem = e.contents[0]

                # After courseList--term in the HTML, the actual courses are listed in a
                # courseList-coursesForTerm in a <a> element
                elif e['class'][0] == 'courseList--coursesForTerm':

                     # Courses are the elements inside and for each we construct a Class
                     # as done previously role is set to the thing before Courses in 
                     # role, href is a relative link in the <a> elements, shortname text gives
                     # something like CS 15
                     for course in e.select("a"):
                         classes.append(Class(self._session, role=role.text[:-len(" Courses")].lower(), href=course["href"], name=course.select_one(".courseBox--shortname").text, semester=curr_sem))
        
        return classes


class Class():
    def __init__(self, session, role, href, name, semester):
        self.role = role
        self._path = href
        self.name = name
        self.semester = semester
        self._session = session
        self.id = int(
            re.search(r"(?<=courses\/)\d+(?=\/?)", self._path).group()
        )

    @property
    @fromPage("/assignments")
    def assignments(self, soup):
        return [
            ProgrammingAssignment(
                name=a.contents[0], href=a["href"], session=self._session
            ) for a in soup.select("td > a:not(:has( >  *))")
        ]

    def __repr__(self):
        return "Class(" + self.name + ", " + self.semester + ", " + self.role + ")"

    def create_assignment(
        self, title, totalPoints, releaseDate, dueDate, **kwargs
    ):
        """
            Creates a new programming assignment
            Takes same parameters as Assignment.edit
        """
        @submitForm("/assignments")
        def createNew(self):
            """
                Creates new assignment, but doesn't modify settings

                Gradescope website sends assignments as multipart/form-data
                But also accepts application/x-www-form-urlencoded

                gradescope "requires" more parameters, but seems
                to default missing ones sensibly. Expect this to break
            """
            return {
                "assignment[type]": "ProgrammingAssignment",
                "assignment[title]": title,
                "assignment[release_date_string]": toGS(releaseDate),
                "assignment[due_date_string]": toGS(dueDate),
            }

        response = createNew(self)

        if not response:
            return None

        assignUrl = getSoup(response.content).select_one("a")["href"]
        href = re.search(r"courses/\d+/assignments/\d+", assignUrl).group()

        assign = ProgrammingAssignment(self._session, title, href=href)
        # Set paramaters for assignment
        assert (assign.edit(title, totalPoints, releaseDate, dueDate, **kwargs))
        return assign


class ProgrammingAssignment():
    def __init__(self, session, name, href):
        self._path = href
        self.name = name
        self._session = session
        self.id = int(
            re.search(r"(?<=assignments\/)\d+(?=\/?)", self._path).group()
        )

    @property
    @fromPage("/submissions")
    def submissions(self, soup):
        return [
            self.Submission(href=a["href"], session=self._session)
            for a in soup.select("td > a:not(:has( >  *))")
        ]

    def __repr__(self):
        return "ProgrammingAssignment(" + self.name + ")"

    @submitForm()
    def delete(self):
        return {"_method": "delete"}

    @submitForm()
    def edit(
        self,
        title: str = NotImplemented,
        totalPoints: int = NotImplemented,
        releaseDate: datetime = NotImplemented,
        dueDate: datetime = NotImplemented,
        *,
        lateDueDate: datetime = NotImplemented,
        groupSize: int = NotImplemented,
        manualGrading: bool = NotImplemented,
        allowGithub: bool = NotImplemented,
        allowUpload: bool = NotImplemented,
        allowBitbucket: bool = NotImplemented,
        leaderboardEntries=NotImplemented,
        memoryLimit: str = NotImplemented,
        autograderTimeout: str = NotImplemented
    ):
        # Atleast one of allowGithub, allowUplod, allowBitbucket needs to be
        # set. Otherwise nothing is done for submission methods
        toEdit = dict(
            kv for kv in locals().items()
            if kv[1] != NotImplemented and kv[0] != "self"
        )

        def snakeCase(name):
            """ camelCase to snake_case """
            # https://stackoverflow.com/a/1176023
            name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

        noLimit = lambda val: val < 0
        submissionMethod = lambda k, v: [
            ("submission_methods[" + k[5:].lower() + "]", v)
        ]
        # TODO: Make this shorter
        generateEntries = defaultdict(
            lambda: lambda k, v: [(k, v)],
            releaseDate=lambda k, v: [(k + "String", v)],
            dueDate=lambda k, v: [(k + "String", v)],
            allowGithub=submissionMethod,
            allowUpload=submissionMethod,
            allowBitbucket=submissionMethod,
            lateDueDate=lambda k, v: [
                ("hardDueDateString", v), ("allowLateSubmissions", bool(v))
            ][int(v is None):],
            groupSize=lambda k, v: [(k, v), ("groupSubmission", bool(v))][
                int(v is None or noLimit(v)):],
            leaderboardEntries=lambda k, v: [
                ("leaderboardMaxEntries", v), ("leaderboardEnabled", bool(v))
            ][int(v is None or noLimit(v)):],
        )
        # Serialize to format that gradescope formrs accepts
        form = dict(
            [
                ("assignment[" + snakeCase(fKey) + "]", toGS(fVal))
                for param, paramValue in toEdit.items()
                for fKey, fVal in generateEntries[param](param, paramValue)
            ]
        )

        form.update(
            {
                "_method": "patch",
                "assignment[type]": "ProgrammingAssignment",
                "commit": "Save"
            }
        )
        return form

    @submitForm(multipart=True)
    def updateAutograder(self, autograderzip):
        return {
            "_method":
                "patch",
            "configuration":
                "zip",
            # if not first time, this is initialized to docker image name
            # seems to work fine if not set
            "assignment[image_name]":
                "",
            "autograder_zip":
                (
                    "autograder.zip", open(autograderzip,
                                           'rb'), "application/x-zip-compressed"
                ),
        }

    class Submission():
        def __init__(self, href, session):
            self._path = href
            self._session = session

        @fromPage()
        def get_testcases(self, soup):
            self.testcases = '\n'.join(
                x["name"] for x in soup.select("div.testCase--header > a")
            )

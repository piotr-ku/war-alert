import json
import os
import time
import requests
import logging
from sources.base import Source
from processors.base import Content, Processor
from processors.unique import ProcessorUnique

url = "https://api.alerts.in.ua/v1/alerts/active.json"

class Alert(Content):
    """
        A class to represent an alert.
    """
    def __init__(self, title, description, pubDate, link):
        """
            Initialize an alert.
        """
        self.title = title
        self.description = description
        self.pubDate = pubDate
        self.link = link

    def __str__(self):
        """
            Return a string representation of an alert.
        """
        return f"{self.title}: {self.description} published at {self.pubDate}"

class SourceAlertsInUa(Source):
    """
        A class to represent the AlertsInUa source.
    """
    def __init__(self, url: str, logger: logging.Logger):
        """
            Initialize the AlertsInUa source.
        """
        self.logger = logger
        self.url = url

    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return [ProcessorUnique]

    def fetch(self, logger) -> list[Alert]:
        """
            Return a list of alerts.
        """
        # Log the URL
        self.logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "AlertsInUa",
            "url": self.url,
        }))

        # Prepare the headers
        headers = {
            "Authorization": f"Bearer {os.environ.get('ALERTSUA_TOKEN')}"
        }

        # Get the alerts
        try:
            response = requests.get(self.url, headers=headers)
        except Exception as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error fetching alerts from alerts.in.ua",
                "exception": str(e),
            }, ensure_ascii=False))
            return []

        # Check the response
        if response.status_code != 200:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error fetching alerts from alerts.in.ua",
                "status": response.status_code,
                "response": response.text,
            }, ensure_ascii=False))
            return []

        # Parse the JSON response
        try:
            alerts = response.json()
            if "alerts" not in alerts:
                return []
            alerts = alerts["alerts"]
        except Exception as e:
            self.logger.error(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "url": self.url,
                "msg": "Error parsing alerts from alerts.in.ua",
                "exception": str(e),
            }, ensure_ascii=False))
            return []

        # Validate the alerts
        if len(alerts) == 0:
            return []

        # Filter alerts by alert type
        alert_type_filter = os.environ.get("ALERTSUA_FILTER_TYPES")
        if alert_type_filter is not None:
            alerts = [alert for alert in alerts \
                if alert["alert_type"] in alert_type_filter.split(",")]

        # Filter alerts by region
        region_filter = os.environ.get("ALERTSUA_FILTER_REGIONS")
        if region_filter is not None:
            alerts = [alert for alert in alerts \
                if alert["location_oblast"] in region_filter.split(",")]

        # Prepare the alerts
        return [self.prepare_alert(alert) for alert in alerts]

    def prepare_alert(self, alert) -> Alert:
        """
            Prepare an alert.
        """
        # Prepare the alert
        alert_type = alert["alert_type"].replace("_", " ").capitalize()
        title = f"{alert_type} alert in {alert['location_title']}"
        pubDate = alert["started_at"]
        link = f"https://alerts.in.ua"

        # Prepare the description
        if "location_raion" in alert:
            description = f"{alert_type} alert in {alert['location_raion']} "\
                f"({alert['location_oblast']})"
        else:
            description = f"{alert_type} alert in {alert['location_oblast']}"

        return Alert(title, description, pubDate, link)

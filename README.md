### monitor service

1. Register a monitor. You need the admin key for this.
```
curl  -H "x-admin-key: bulubala" -XPOST http://localhost:8000/monitors \
-H "content-type: application/json" \
-d '{"frequency": "86400", "name": "first-monitor", "slug": "first-monitor"}'
```

You'll get a json block back, make note of the URL to call and API key.
```
{
  "api_key": "TGRKXAOML96XV03S",
  "monitor_url": "https://foo.bar/monitor/second-monitor",
  "name": "first-monitor",
  "report_if_not_called_in": 86400
}

```
2. Call your monitor. Must be a POST request with empty body.
```
curl -XPOST https://localhost:8000/monitor/second-monitor -H "x-api-key: TGRKXAOML96XV03S"curl https://localhost:8000/monitor/second-monitor -H "x-api-key: TGRKXAOML96XV03Scurl https://localhost:8000/monitor/second-monitor -H "x-api-key: TGRKXAOML96XV03S"
```

3. If you haven't called the monitor in 86400 seconds (a day), the webhook fires.

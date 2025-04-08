### monitor service

1. Register a monitor. You need the admin key for this.
   - frequency: fire an alert if this monitor hasn't been called in this long (seconds)
   - name: human-readable name
   - slug: urlizable name, a-z0-9-{1,63}
   - webhook: webhook URL to call if we need to fire an alert
   - webhook_type: GET or POST for the webhook call.
   - webhook_headers: dict of header:value pairs to send with the webhook request
   - webhook_form_fields: dict of field:value pairs to send with the webhook request as a FORM
   - webhook_payload: string payload to send with the webhook request as the BODY.
   - (TBD)
```
curl  -H "x-admin-key: bulubala" -XPOST http://localhost:8000/monitors \
-H "content-type: application/json" \
-d '{"frequency": "86400", "name": "first-monitor", "slug": "first-monitor","webhook_type": "post", \
"webhook_url": "https://api.pushover.net/1/messages.json", "webhook_headers": {}, \
"webhook_form_fields": {"k/v pairs, a nightmare to escape"}, webhook_payload: ""'

'
```
(For pushover, we only need webhook_form_fields)

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

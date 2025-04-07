# Flyrestarter

It rhymes with "firestarter".


## What

Flyrestarter monitors the Fly.io apps you specify in the config file. If it notices a machine is in state "started" and is failing a health check, it can take any combination of the following actions to try to restore the machine or call someone's attention to it:

    * Restarting the machine
    * Sending an alert

## How

Yaml config file

```yaml
api:
 fly_api_token: FOOOO
 organization: BAAR
apps:
- name: myapp
  process_groups:
  - foo
  - bar
  actions:
  - type: restart
    after_min: 10
  - type: notify
notifications:
  - type: pushover
    user_keys:
    - XXXXXXX
    - YYYYYYY
    api_token: ZZZZZZZZZZZZZZZ
  - type: email
    addresses:
    - foo@bar.com
    - bar@bar.com
```

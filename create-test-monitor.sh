{"token": "agy5bng4vyd16m4k5qpm9a1qvewfof","user":"uMRezmA6xe16KqbHDFQPfuj92cFgJE", "title": "monitor alert", "message": "monitor has not been hit in 60 seconds", "priority": "0"}


curl  -H "x-admin-key: bulubala" -XPOST http://localhost:8000/monitors -H "content-type: application/json" -d '{"frequency": "60", "name": "first-monitor", "slug": "sekond-monitor", "webhook":{"url":"https://ubunty.fly.dev", "method": "post", "form_fields": WTAF}}'

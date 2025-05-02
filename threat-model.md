### Threat model

too fancy a term.


- We do no email verification so anyone can register any number of accounts.
    * add email verification
    * add email normalization to sidestep the plus-address workaround
    * captcha of proof-of-work of some kind?
- Each account can create any number of webhooks, only limited by slug uniqueness
    * But in order for those webhooks to be an attack vector, the user has to spend resources calling their monitor endpoints
    * therefore this would DDoS us but not use us an external attack vector
    * we only check once every minute so the volume would be pathetic anyway
- webhook payloads are not really validated or limited in size
    * add size limits for payloads
    * validate the ones that should be dicts or json
- payloads can contain sensitive data and it's opaque so we don't know
    * encrypt payloads to protect against db steal?
    * but if someone steals the db it means they have local access so they already have the key
    * the KMS thing would help here?

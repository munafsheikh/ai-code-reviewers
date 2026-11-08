Find security defects introduced by the added lines:
- injection: SQL/NoSQL/LDAP/OS command/template injection from untrusted input
- unsafe deserialisation, dynamic code evaluation, path traversal, SSRF
- broken authentication/authorisation checks, insecure randomness for secrets
- disabled TLS verification, weak cryptography for security purposes
Report only issues visible in the added lines. Severity "critical" requires a plausible exploit path.

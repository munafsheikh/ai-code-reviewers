# Code review examples

Real changes and what the reviewer reports for them. Every output on this page was produced
by `munafsheikh/ai-code-reviewers` with the `offline` profile (deterministic rules only), so
you get exactly the same result. With a model (`balanced`), model findings are added and
marked as *hypotheses*.

Set this once for the commands below:

```bash
acr() { docker run --rm -i --read-only --network none munafsheikh/ai-code-reviewers:0.10.1 "$@"; }
```

## Review your branch before you push

```bash
git diff main... | acr review --profile offline
```

Only lines your branch **adds** are reviewed, so existing code is not re-reported. Limit
to some files with Git pathspecs: `git diff main... -- '*.py' 'src/**'`.

Keep every format for tooling:

```bash
mkdir -p out && chmod 0777 out
git diff main... | docker run --rm -i --read-only --network none -v "$PWD/out:/out" \
  munafsheikh/ai-code-reviewers:0.10.1 review --profile offline --format json,sarif,markdown --out-dir /out
jq -r '.findings[] | "\(.severity)\t\(.rule_id)\t\(.location.path):\(.location.start_line)\t\(.title)"' out/review.json
jq -r '.gate.status' out/review.json      # pass | warn | block | error
```

## Example 1: unsafe Python

The change ([`benchmarks/fixtures/python-unsafe`](https://github.com/munafsheikh/ai-code-reviewers/blob/main/benchmarks/fixtures/python-unsafe/diff.patch)):

```python
def run(cmd, env={}):
    return subprocess.run(cmd, shell=True, env=env)


def restore(blob):
    return pickle.loads(blob)


def fetch(url):
    try:
        return requests.get(url, verify=False, timeout=5).json()
    except Exception:
        pass
```

The review (exit code `1`, blocked):

| | Location | Finding | Basis |
|---|---|---|---|
| critical | `svc/jobs.py:9` | **Shell command built from variables** | hypothesis, rule, medium |
| major | `svc/jobs.py:13` | **Unsafe deserialisation** | hypothesis, rule, medium |
| major | `svc/jobs.py:18` | **TLS certificate verification disabled** | verified, rule, high |
| major | `svc/jobs.py:19` | **Swallowed exception** | verified, rule, high |
| minor | `svc/jobs.py:8` | **Mutable default argument** | verified, rule, high |

Each finding comes with an explanation, the evidence (secrets redacted) and a fix, e.g.:

> **INJ-003** — svc/jobs.py:9. Passing interpolated strings to a shell enables command injection.
> Evidence: `return subprocess.run(cmd, shell=True, env=env)`.
> Fix: Pass an argument list without a shell (`subprocess.run([...])`, `ProcessBuilder`, `execFile`).

*verified* findings are deterministic matches of high-confidence rules; *hypothesis*
findings need a human look. Rule ids link to the [rule reference](../generated/rules.md).

## Example 2: Java data access

```java
public User find(Connection conn, String id) throws SQLException {
    String q = "SELECT * FROM users WHERE id = '" + id + "'";
    ResultSet rs = conn.createStatement().executeQuery(q);
    return map(rs);
}

public byte[] loadAvatar(String path) {
    try {
        FileInputStream in = new FileInputStream(path);
        return in.readAllBytes();
    } catch (Exception e) {}
    return null;
}
```

| | Location | Finding | Basis |
|---|---|---|---|
| critical | `src/main/java/app/UserDao.java:9` | **SQL built by string concatenation** | hypothesis, rule, medium |
| major | `src/main/java/app/UserDao.java:16` | **Closeable opened outside try-with-resources** | hypothesis, rule, medium |
| major | `src/main/java/app/UserDao.java:18` | **Swallowed exception** | verified, rule, high |

## Example 3: a deployment change without docs

Not every finding is about code. The documentation checks treat build, CI and deployment
definitions, new `make` targets, CLI options, environment variables and API schemas as
user-facing: changing them without touching any docs blocks the review.

```diff
--- a/.github/workflows/deploy.yml
+++ b/.github/workflows/deploy.yml
@@ -10,3 +10,4 @@ jobs:
   deploy:
     runs-on: ubuntu-latest
+    environment: production
     steps:
```

| | Location | Finding | Basis |
|---|---|---|---|
| major | `.github/workflows/deploy.yml:12` | **Build, CI or deployment definition changed without documentation** | hypothesis, rule, medium |

Fix: update the README / docs page that describes this pipeline (and the CHANGELOG), or note
in the PR why no user-visible behaviour changed. Version or digest bumps (`uses:`, `FROM`,
`image:`) do not trigger it, so dependency updates stay quiet.

## Example 4: a change that tries to talk the reviewer out of it

[`benchmarks/fixtures/prompt-injection`](https://github.com/munafsheikh/ai-code-reviewers/blob/main/benchmarks/fixtures/prompt-injection/diff.patch)
adds code comments addressed to "the AI reviewer" claiming the file is pre-approved and
dictating an empty verdict, plus a hard-coded API key. The rules flag the key (`SEC-004`,
major: blocked) regardless of what the comments say, and the model sees the whole diff only
inside an untrusted-data fence that the diff cannot close. Benchmarks assert this case
blocks on every release.

## Example 5: review a feature request before anyone builds it

```bash
gh issue view 52 --json number,title,body,labels,url | acr review --issue - --profile offline
```

For an issue whose whole body is *"Checkout should be fast and user-friendly for all
customers."*:

| | Location | Finding | Basis |
|---|---|---|---|
| major | `@issue/52:1` | **Missing acceptance criteria** | verified, rule, high |
| minor | `@issue/52:5` | **Untestable wording** | hypothesis, rule, medium |

Fix: add an `## Acceptance criteria` section (a checklist or Given/When/Then a test can
verify) and replace "fast" and "user-friendly" with observable statements.

## Example 6: team rules on top

With the custom image from [Customize reviews](customize.md#your-own-image), a team rule and
team instructions apply to every review:

```bash
printf -- '--- a/billing/pay.py\n+++ b/billing/pay.py\n@@ -0,0 +1 @@\n+total = float(amount) * 1.2\n' \
  | docker run --rm -i --read-only --network none my-org/code-reviewer review --profile offline
```

Result: blocked by `MON-001` *Float used for a money amount*, and the report lists
`Team instructions: 10-team.md` so the guidance used is on record.

## Example 7: one lane at a time, then merge

Large teams split reviews into parallel lanes (this project's CI does: code, security,
docs). Any lane is a normal review narrowed with `--skills`; `acr merge` combines them,
judges coverage across all lanes and applies one gate:

```bash
mkdir -p out && chmod 0777 out
for lane in "code=code-quality.*,maintainability.*,testing.*,lang.*" "security=security.*" "docs=documentation.*"; do
  git diff main... | docker run --rm -i --read-only --network none -v "$PWD/out:/out" \
    munafsheikh/ai-code-reviewers:0.10.1 review --profile offline --skills "${lane#*=}" \
    --format json --out-dir "/out/${lane%%=*}"
done
docker run --rm --read-only --network none -v "$PWD/out:/out" munafsheikh/ai-code-reviewers:0.10.1 \
  merge /out/code/review.json /out/security/review.json /out/docs/review.json --names code,security,docs
```

The merged report says `Parallel reviews: code (… skills), security (…), docs (…)`; a file
no lane covered blocks it.

## Example 8: as a Git pre-push hook

```bash
# .git/hooks/pre-push (chmod +x)
#!/bin/sh
git diff origin/main...HEAD | docker run --rm -i --read-only --network none \
  munafsheikh/ai-code-reviewers:0.10.1 review --profile offline
```

A non-zero exit stops the push; `git push --no-verify` skips it when you must.

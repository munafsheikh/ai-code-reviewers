from orchestrator.engine import diff

GIT = """diff --git a/src/A.java b/src/A.java
index 1..2 100644
--- a/src/A.java
+++ b/src/A.java
@@ -1,3 +1,4 @@
 class A {
+  int x;
--- removed line that looks like a header
 }
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
diff --git a/n.py b/n.py
new file mode 100644
--- /dev/null
+++ b/n.py
@@ -0,0 +1,2 @@
+import os
+print(1)
"""


def test_git_diff_files_and_line_numbers():
    files = diff.parse(GIT)
    assert [f.path for f in files] == ["src/A.java", "n.py"]
    assert files[0].added == [(2, "  int x;")]
    assert files[1].added == [(1, "import os"), (2, "print(1)")]
    assert files[0].language == "java" and files[1].language == "python"


def test_plain_unified_diff_multiple_files():
    d = "--- a/x.py\t2020\n+++ b/x.py\t2020\n@@ -5,2 +5,3 @@\n a\n+b\n--- y.py\n+++ y.py\n@@ -0,0 +1 @@\n+z\n"
    files = diff.parse(d)
    assert [(f.path, f.added) for f in files] == [("x.py", [(6, "b")]), ("y.py", [(1, "z")])]


def test_multiple_hunks_and_crlf():
    d = "--- a/f.js\r\n+++ b/f.js\r\n@@ -1,1 +1,2 @@\r\n a\r\n+b\r\n@@ -10,1 +11,2 @@\r\n c\r\n+d\r\n"
    (f,) = diff.parse(d)
    assert f.added == [(2, "b"), (12, "d")]


def test_empty_and_garbage():
    assert diff.parse("") == []
    assert diff.parse("not a diff at all\n") == []


def test_chunking_keeps_files_whole_and_reports_oversized():
    files = diff.parse(GIT)
    chunks, skipped = diff.chunk(files, max_chars=10_000)
    assert len(chunks) == 1 and skipped == []
    chunks, skipped = diff.chunk(files, max_chars=60)
    assert skipped and all(len(diff.render(c)) <= 60 for c in chunks)


def test_matches_globs_languages_excludes():
    (f,) = [x for x in diff.parse(GIT) if x.path == "src/A.java"]
    assert f.matches(["*.java"], ["java"])
    assert not f.matches(["*.java"], ["python"])
    assert f.matches(["*"], ["*"])
    assert not f.matches(["*"], ["*"], exclude=["src/*"])

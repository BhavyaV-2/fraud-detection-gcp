# Publish to GitHub

Run these commands from this project's root in PowerShell. Git is available;
GitHub CLI is optional. Replace `YOUR_USERNAME` with your actual GitHub username.

## Review the upload

```powershell
git init -b main
git status --short --untracked-files=all
git status --short --ignored
git add --dry-run .
git check-ignore .env.local src/process_transaction/model.pkl "dashboard (1).html"
```

The upload should contain the source, tests, main dashboard, deployment script,
requirements, documentation, and GitHub workflow. Assignment reports, local
configuration, credentials, environments, and generated model files stay local.
Review new files for secrets before each commit; ignore patterns cannot identify
every possible credential filename or secret embedded in source code.

## Create the first commit

```powershell
git add .
git diff --cached --stat
git diff --cached --check
git commit -m "Prepare fraud detection pipeline for GitHub"
```

If Git asks for your identity, set `git config user.name "Your Name"` and
`git config user.email "YOUR_GITHUB_NOREPLY_EMAIL"`, then repeat the commit.

## Push using the GitHub website

Create an **empty** repository named `fraud-detection-gcp` on GitHub. Leave its
README, license, and gitignore options unchecked because the local project
already contains its own files. Then run:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/fraud-detection-gcp.git
git push -u origin main
```

Git may open a browser to authenticate. Use the Git Credential Manager flow or
an appropriate token; never put a token directly into the remote URL.

Alternatively, if GitHub CLI is installed:

```powershell
gh auth login
gh repo create fraud-detection-gcp --public --source=. --remote=origin --push
```

Choose either publishing path. Use `--private` instead of `--public` if desired.

## Repository presentation

- Description: `Serverless transaction anomaly detection with Google Cloud Functions, Pub/Sub, Firestore, and Isolation Forest.`
- Topics: `python`, `google-cloud`, `pubsub`, `firestore`, `anomaly-detection`, `isolation-forest`, `serverless`.
- Check the Actions tab after pushing and confirm the test workflow passes.
- Add a screenshot using synthetic data and a short demo video when available.
- Choose a license after confirming ownership and any academic project rules.
- Describe measured results only; synthetic examples and browser estimates do
  not establish fraud accuracy or end-to-end processing throughput.

## Later updates

```powershell
git status
git add .
git diff --cached --stat
git commit -m "Describe your change"
git push
```

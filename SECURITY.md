# Security policy

This is a portfolio project, not a supported product, but reports are welcome.

To report a vulnerability, use GitHub's private reporting: **Security > Report a vulnerability** on this repository. Please do not open a public issue for it.

Never commit secrets. `.env` files are git-ignored, and secret scanning with push protection is enabled on this repository. A gitleaks scan also runs on every commit (pre-commit) and in CI.

## If a secret leaks

This repository is public, so assume a pushed secret is already copied. In this order:

1. **Revoke or rotate it** at the provider (Neon, Vercel, an API key page). Do this first: deleting the file or rewriting history does not undo the exposure.
2. Check the provider's usage and billing for activity you did not make.
3. Look at the repository's **Security > Secret scanning** alerts and close the one for this secret once it is rotated.
4. Remove the secret from the code, and if it is in history, clean the history only after step 1.
5. Put the new value in the service's environment settings, never in a file in the repository.

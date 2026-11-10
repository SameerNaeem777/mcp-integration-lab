# Mergington High School Activities API

A FastAPI application that lets students discover activities and manage their own enrollments, with role-protected staff rosters.

## Features

- Browse activities and availability without exposing student contact details
- Sign in as a student, teacher, or administrator
- Let students view and manage only their own enrollments
- Let teachers view rosters for assigned activities and administrators view all rosters

## Getting Started

1. Install the dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Configure authentication before signing in. The application requires:

   - `AUTH_TOKEN_SECRET`: a random secret of at least 32 bytes.
   - `AUTH_USERS`: a JSON object keyed by username. Each user has a PBKDF2-SHA256 `password_hash` and a `role` of `student`, `teacher`, or `administrator`. Student usernames must be lowercase email addresses. Teachers also require an `activities` list.

   Generate a password hash at a terminal prompt (the password is not echoed):

   ```
   python -c 'from getpass import getpass; from src.app import hash_password; print(hash_password(getpass()))'
   ```

   Example configuration shape (replace each placeholder with a generated password hash and use a unique secret):

   ```sh
   export AUTH_TOKEN_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   export AUTH_USERS='{"student@mergington.edu":{"password_hash":"pbkdf2_sha256$...","role":"student"},"teacher@mergington.edu":{"password_hash":"pbkdf2_sha256$...","role":"teacher","activities":["Chess Club"]},"admin@mergington.edu":{"password_hash":"pbkdf2_sha256$...","role":"administrator"}}'
   ```

   Store these values in an untracked secret manager or local environment, never in source control. The server remains browsable without auth configuration, but sign-in returns `503` until both settings are present.

3. In the same terminal where you configured the environment, start the application and open it at http://localhost:8000. API documentation is available at http://localhost:8000/docs.

   ```
   uvicorn src.app:app --reload
   ```

## API Endpoints

| Method | Endpoint                                   | Access                            | Description                                       |
| ------ | ------------------------------------------ | --------------------------------- | ------------------------------------------------- |
| POST   | `/auth/login`                              | Public                            | Exchange username/password for a short-lived token |
| GET    | `/activities`                              | Public                            | List activity details and counts, without emails  |
| GET    | `/me/enrollments`                          | Student                           | View the authenticated student's enrollments      |
| POST   | `/activities/{activity_name}/signup`       | Student or scoped staff           | Enroll self, or have staff enroll a student       |
| DELETE | `/activities/{activity_name}/unregister`   | Student or scoped staff           | Unenroll self, or have staff remove a student     |
| GET    | `/activities/{activity_name}/participants` | Assigned teacher or administrator | View an authorized roster                         |

Access tokens are signed with PyJWT using HMAC-SHA256 and expire after 15 minutes. A student's identity is derived from the validated token, not request parameters. Teachers can view and manage rosters only for activities listed in their configured scope; administrators can view and manage any roster. Staff provide the target student as `{"student_email":"student@mergington.edu"}` in the request body; new enrollments require a configured student account. Students cannot provide a target email and can manage only their own enrollment. Student records are not included in the public activity listing.

## Tests

Install the test dependency and run the API access-control tests:

```
pip install -r requirements-dev.txt
python -m unittest discover -s tests
```

Activity and enrollment data remain in memory and reset when the server restarts; persistent storage is tracked separately.

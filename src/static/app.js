document.addEventListener("DOMContentLoaded", () => {
  const activitiesList = document.getElementById("activities-list");
  const activitySelect = document.getElementById("activity");
  const signupForm = document.getElementById("signup-form");
  const signupContainer = document.getElementById("signup-container");
  const loginForm = document.getElementById("login-form");
  const logoutButton = document.getElementById("logout-button");
  const accountStatus = document.getElementById("account-status");
  const enrollmentsList = document.getElementById("enrollments-list");
  const messageDiv = document.getElementById("message");
  let accessToken = null;
  let currentUser = null;

  async function apiRequest(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (accessToken) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }
    const response = await fetch(url, { ...options, headers });
    const result = await response.json();
    return { response, result };
  }

  function showMessage(message, type) {
    messageDiv.textContent = message;
    messageDiv.className = type;
    messageDiv.classList.remove("hidden");
  }

  function makeButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
  }

  async function refreshActivities() {
    try {
      const { response, result: activities } = await apiRequest("/activities");
      if (!response.ok) {
        throw new Error(activities.detail || "Failed to load activities.");
      }

      activitiesList.replaceChildren();
      activitySelect.replaceChildren(new Option("-- Select an activity --", ""));

      Object.entries(activities).forEach(([name, details]) => {
        const card = document.createElement("article");
        card.className = "activity-card";

        const heading = document.createElement("h4");
        heading.textContent = name;
        const description = document.createElement("p");
        description.textContent = details.description;
        const schedule = document.createElement("p");
        schedule.textContent = `Schedule: ${details.schedule}`;
        const availability = document.createElement("p");
        availability.textContent = `Availability: ${details.available_spots} spots left`;
        card.append(heading, description, schedule, availability);

        if (currentUser && ["teacher", "administrator"].includes(currentUser.role)) {
          card.append(
            makeButton("View roster", () => showRoster(card, name))
          );
        }

        const option = new Option(name, name);
        activitySelect.add(option);
        activitiesList.append(card);
      });
    } catch (error) {
      activitiesList.replaceChildren();
      const errorText = document.createElement("p");
      errorText.textContent = "Failed to load activities. Please try again later.";
      activitiesList.append(errorText);
      console.error("Error fetching activities:", error);
    }
  }

  async function showRoster(card, activityName) {
    const roster = document.createElement("div");
    roster.className = "roster";
    const heading = document.createElement("h5");
    heading.textContent = "Participants";
    roster.append(heading);
    try {
      const { response, result } = await apiRequest(
        `/activities/${encodeURIComponent(activityName)}/participants`
      );
      if (!response.ok) {
        throw new Error(result.detail || "Failed to load roster.");
      }
      if (result.participants.length === 0) {
        const empty = document.createElement("p");
        empty.textContent = "No participants yet.";
        roster.append(empty);
      } else {
        const list = document.createElement("ul");
        result.participants.forEach((email) => {
          const item = document.createElement("li");
          const address = document.createElement("span");
          address.textContent = email;
          item.append(address);
          item.append(
            makeButton("Unregister", () =>
              updateRoster(activityName, "DELETE", email)
            )
          );
          list.append(item);
        });
        roster.append(list);
      }

      const registerForm = document.createElement("form");
      registerForm.className = "roster-register-form";
      const emailInput = document.createElement("input");
      emailInput.type = "email";
      emailInput.name = "student_email";
      emailInput.placeholder = "student@mergington.edu";
      emailInput.required = true;
      emailInput.setAttribute("aria-label", "Student email");
      const registerButton = document.createElement("button");
      registerButton.type = "submit";
      registerButton.textContent = "Register student";
      registerForm.append(emailInput, registerButton);
      registerForm.addEventListener("submit", (event) => {
        event.preventDefault();
        updateRoster(activityName, "POST", emailInput.value);
      });
      roster.append(registerForm);
    } catch (error) {
      const errorText = document.createElement("p");
      errorText.textContent = error.message;
      roster.append(errorText);
    }
    card.querySelector(".roster")?.remove();
    card.append(roster);
  }

  async function updateRoster(activityName, method, studentEmail) {
    try {
      const { response, result } = await apiRequest(
        `/activities/${encodeURIComponent(activityName)}/${
          method === "POST" ? "signup" : "unregister"
        }`,
        {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student_email: studentEmail }),
        }
      );
      if (!response.ok) {
        throw new Error(result.detail || "Failed to update roster.");
      }
      showMessage(result.message, "success");
      await refreshActivities();
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function refreshEnrollments() {
    enrollmentsList.replaceChildren();
    if (!currentUser || currentUser.role !== "student") {
      const item = document.createElement("li");
      item.textContent = "Sign in as a student to view your activities.";
      enrollmentsList.append(item);
      return;
    }

    try {
      const { response, result } = await apiRequest("/me/enrollments");
      if (!response.ok) {
        throw new Error(result.detail || "Failed to load your activities.");
      }
      if (result.activities.length === 0) {
        const item = document.createElement("li");
        item.textContent = "You are not registered for any activities.";
        enrollmentsList.append(item);
        return;
      }

      result.activities.forEach((activity) => {
        const item = document.createElement("li");
        item.append(document.createTextNode(activity.name));
        item.append(
          makeButton("Unregister", async () => {
            try {
              const { response: unregisterResponse, result: unregisterResult } =
                await apiRequest(
                  `/activities/${encodeURIComponent(activity.name)}/unregister`,
                  { method: "DELETE" }
                );
              if (!unregisterResponse.ok) {
                throw new Error(
                  unregisterResult.detail || "Failed to unregister."
                );
              }
              showMessage(unregisterResult.message, "success");
              await Promise.all([refreshActivities(), refreshEnrollments()]);
            } catch (error) {
              showMessage(error.message, "error");
            }
          })
        );
        enrollmentsList.append(item);
      });
    } catch (error) {
      const item = document.createElement("li");
      item.textContent = error.message;
      enrollmentsList.append(item);
    }
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: formData.get("username"),
          password: formData.get("password"),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || "Sign in failed.");
      }
      accessToken = result.access_token;
      currentUser = result.user;
      loginForm.classList.add("hidden");
      logoutButton.classList.remove("hidden");
      accountStatus.textContent = `Signed in as ${currentUser.username} (${currentUser.role})`;
      accountStatus.className = "account-status";
      signupContainer.classList.toggle("hidden", currentUser.role !== "student");
      await Promise.all([refreshActivities(), refreshEnrollments()]);
      showMessage("Signed in successfully.", "success");
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  logoutButton.addEventListener("click", async () => {
    accessToken = null;
    currentUser = null;
    loginForm.reset();
    loginForm.classList.remove("hidden");
    logoutButton.classList.add("hidden");
    accountStatus.classList.add("hidden");
    signupContainer.classList.add("hidden");
    await Promise.all([refreshActivities(), refreshEnrollments()]);
    showMessage("Signed out.", "info");
  });

  signupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const activity = activitySelect.value;
    try {
      const { response, result } = await apiRequest(
        `/activities/${encodeURIComponent(activity)}/signup`,
        { method: "POST" }
      );
      if (!response.ok) {
        throw new Error(result.detail || "An error occurred.");
      }
      signupForm.reset();
      showMessage(result.message, "success");
      await Promise.all([refreshActivities(), refreshEnrollments()]);
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  refreshActivities();
  refreshEnrollments();
});

// CampusSync Client-Side Interactions & Role Switching

document.addEventListener('DOMContentLoaded', function () {
  // 1. Password Visibility Toggle
  const toggleButtons = document.querySelectorAll('.toggle-pwd-btn');
  toggleButtons.forEach(btn => {
    btn.addEventListener('click', function () {
      const targetId = this.getAttribute('data-target');
      const input = document.getElementById(targetId);
      const icon = this.querySelector('i');

      if (!input) return;

      if (input.type === 'password') {
        input.type = 'text';
        icon.classList.remove('bi-eye');
        icon.classList.add('bi-eye-slash');
        this.setAttribute('aria-label', 'Hide password');
      } else {
        input.type = 'password';
        icon.classList.remove('bi-eye-slash');
        icon.classList.add('bi-eye');
        this.setAttribute('aria-label', 'Show password');
      }
    });
  });

  // 2. Role Selection Tabs (Student / Teacher)
  const studentTab = document.getElementById('role-student-btn');
  const teacherTab = document.getElementById('role-teacher-btn');
  const studentForm = document.getElementById('student-login-section');
  const teacherForm = document.getElementById('teacher-login-section');

  function setRole(role) {
    if (role === 'teacher') {
      if (teacherTab) teacherTab.classList.add('active');
      if (studentTab) studentTab.classList.remove('active');
      if (teacherForm) teacherForm.style.display = 'block';
      if (studentForm) studentForm.style.display = 'none';
      if (window.history.replaceState) {
        const url = new URL(window.location);
        url.searchParams.set('role', 'teacher');
        window.history.replaceState({}, '', url);
      }
    } else {
      if (studentTab) studentTab.classList.add('active');
      if (teacherTab) teacherTab.classList.remove('active');
      if (studentForm) studentForm.style.display = 'block';
      if (teacherForm) teacherForm.style.display = 'none';
      if (window.history.replaceState) {
        const url = new URL(window.location);
        url.searchParams.set('role', 'student');
        window.history.replaceState({}, '', url);
      }
    }
  }

  if (studentTab && teacherTab) {
    studentTab.addEventListener('click', function (e) {
      e.preventDefault();
      setRole('student');
    });

    teacherTab.addEventListener('click', function (e) {
      e.preventDefault();
      setRole('teacher');
    });
  }

  // 3. Student Form Client Validation
  const studentFormElem = document.getElementById('student-login-form');
  if (studentFormElem) {
    studentFormElem.addEventListener('submit', function (e) {
      const emailInput = document.getElementById('student_email');
      const codeInput = document.getElementById('student_class_code');
      if (!emailInput.value.trim()) {
        alert('Please enter your student email address.');
        emailInput.focus();
        e.preventDefault();
        return;
      }
      if (!codeInput.value.trim()) {
        alert('Please enter your class code provided by your teacher.');
        codeInput.focus();
        e.preventDefault();
        return;
      }
    });
  }

  // 4. Registration Form Client Validation
  const registerForm = document.getElementById('teacher-register-form');
  if (registerForm) {
    const passwordInput = document.getElementById('reg_password');
    const pwdFeedback = document.getElementById('pwd-length-feedback');

    if (passwordInput && pwdFeedback) {
      passwordInput.addEventListener('input', function () {
        if (this.value.length < 8) {
          pwdFeedback.textContent = `Password length: ${this.value.length}/8 characters minimum`;
          pwdFeedback.style.color = '#dc2626';
        } else {
          pwdFeedback.textContent = 'Password meets length requirement (8+ chars)';
          pwdFeedback.style.color = '#16a34a';
        }
      });
    }

    registerForm.addEventListener('submit', function (e) {
      const emailInput = document.getElementById('reg_email');
      const fullNameInput = document.getElementById('reg_full_name');

      if (!fullNameInput.value.trim()) {
        alert('Please enter your Full Name.');
        fullNameInput.focus();
        e.preventDefault();
        return;
      }

      if (!emailInput.value.trim() || !emailInput.checkValidity()) {
        alert('Please enter a valid email address.');
        emailInput.focus();
        e.preventDefault();
        return;
      }

      if (passwordInput.value.length < 8) {
        alert('Password must be at least 8 characters long.');
        passwordInput.focus();
        e.preventDefault();
        return;
      }
    });
  }

  // 5. Global Search Bar for Dashboard, Assignment Management, Written Test Management & other modules
  const searchInputs = document.querySelectorAll('.dash-search-input, #assignmentSearchInput');

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function filterAllTables(rawQuery) {
    const query = (rawQuery || '').trim().toLowerCase();
    const tables = document.querySelectorAll('.dash-table, table.dash-table');

    tables.forEach(table => {
      const tbody = table.querySelector('tbody');
      if (!tbody) return;

      const rows = tbody.querySelectorAll('tr:not(.search-no-results-row)');
      if (rows.length === 0) return;

      let matchCount = 0;

      rows.forEach(row => {
        if (!query) {
          row.style.display = '';
          matchCount++;
        } else {
          let rowText = (row.textContent || row.innerText || '').toLowerCase();
          const inputs = row.querySelectorAll('input, select, textarea');
          inputs.forEach(inp => {
            if (inp.value) {
              rowText += ' ' + inp.value.toLowerCase();
            }
          });

          if (rowText.includes(query)) {
            row.style.display = '';
            matchCount++;
          } else {
            row.style.display = 'none';
          }
        }
      });

      // Handle "No results found" row in table
      let noResultsRow = tbody.querySelector('.search-no-results-row');
      if (query && matchCount === 0) {
        if (!noResultsRow) {
          noResultsRow = document.createElement('tr');
          noResultsRow.className = 'search-no-results-row';
          const thCount = table.querySelectorAll('thead th').length || 6;
          noResultsRow.innerHTML = `
            <td colspan="${thCount}" class="text-center py-4 text-muted">
              <i class="bi bi-search me-2 text-primary"></i>
              No results found matching "<strong>${escapeHtml(rawQuery.trim())}</strong>"
            </td>
          `;
          tbody.appendChild(noResultsRow);
        } else {
          noResultsRow.style.display = '';
          const strong = noResultsRow.querySelector('strong');
          if (strong) strong.textContent = rawQuery.trim();
        }
      } else {
        if (noResultsRow) {
          noResultsRow.remove();
        }
      }
    });

    // Synchronize inputs across the page
    searchInputs.forEach(input => {
      if (input.value !== rawQuery) {
        input.value = rawQuery;
      }
    });
  }

  window.filterAllTables = filterAllTables;

  window.filterAssignmentsTable = function () {
    const assignInput = document.getElementById('assignmentSearchInput');
    const query = assignInput ? assignInput.value : '';
    filterAllTables(query);
  };

  searchInputs.forEach(input => {
    // Real-time filtering as the user types
    input.addEventListener('input', function () {
      filterAllTables(this.value);
    });

    // Handle Enter and Escape key presses
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        filterAllTables(this.value);
      } else if (e.key === 'Escape') {
        this.value = '';
        filterAllTables('');
      }
    });
  });

  // Automatically apply URL parameter 'q' on page load if present
  const searchUrlParams = new URLSearchParams(window.location.search);
  const initialSearchQuery = searchUrlParams.get('q');
  if (initialSearchQuery) {
    searchInputs.forEach(input => input.value = initialSearchQuery);
    filterAllTables(initialSearchQuery);
  }
});

// Student Assignment File Upload Live Preview & Validation Helpers
function handleStudentFileSelection(input, infoContainerId, removeBtnId, submitBtnId) {
  const infoContainer = document.getElementById(infoContainerId);
  const removeBtn = document.getElementById(removeBtnId);
  const submitBtn = submitBtnId ? document.getElementById(submitBtnId) : null;
  if (!infoContainer) return;

  if (input.files && input.files[0]) {
    const file = input.files[0];
    const maxSizeBytes = 10 * 1024 * 1024; // 10 MB limit
    const sizeKb = (file.size / 1024).toFixed(1);
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    const sizeFormatted = file.size > 1024 * 1024 ? `${sizeMb} MB` : `${sizeKb} KB`;

    const allowedExtensions = ['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'];
    const fileExt = file.name.split('.').pop().toLowerCase();

    if (!allowedExtensions.includes(fileExt)) {
      infoContainer.innerHTML = `
        <div class="alert alert-danger py-2 px-3 mb-0 small d-flex align-items-center gap-2 border">
          <i class="bi bi-exclamation-octagon-fill text-danger fs-6"></i>
          <div>Unsupported format <strong>.${fileExt}</strong>. Allowed formats: <strong>PDF, DOC, DOCX, JPG, PNG</strong>.</div>
        </div>`;
      if (removeBtn) removeBtn.classList.remove('d-none');
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    if (file.size === 0) {
      infoContainer.innerHTML = `
        <div class="alert alert-danger py-2 px-3 mb-0 small d-flex align-items-center gap-2 border">
          <i class="bi bi-exclamation-octagon-fill text-danger fs-6"></i>
          <div>The selected file is empty (0 bytes). Please choose a valid document.</div>
        </div>`;
      if (removeBtn) removeBtn.classList.remove('d-none');
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    if (file.size > maxSizeBytes) {
      infoContainer.innerHTML = `
        <div class="alert alert-danger py-2 px-3 mb-0 small d-flex align-items-center gap-2 border">
          <i class="bi bi-exclamation-octagon-fill text-danger fs-6"></i>
          <div>File exceeds 10 MB limit (<strong>${sizeFormatted}</strong>). Please choose a smaller file.</div>
        </div>`;
      if (removeBtn) removeBtn.classList.remove('d-none');
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    // Success preview
    infoContainer.innerHTML = `
      <div class="alert alert-success py-2 px-3 mb-0 small d-flex justify-content-between align-items-center border">
        <div class="d-flex align-items-center gap-2">
          <i class="bi bi-file-earmark-check-fill text-success fs-5"></i>
          <div>
            <strong class="text-dark">${file.name}</strong>
            <span class="badge bg-white text-secondary border ms-2">${sizeFormatted}</span>
          </div>
        </div>
      </div>`;
    if (removeBtn) removeBtn.classList.remove('d-none');
    if (submitBtn) submitBtn.disabled = false;
  } else {
    infoContainer.innerHTML = '';
    if (removeBtn) removeBtn.classList.add('d-none');
    if (submitBtn) submitBtn.disabled = false;
  }
}

function clearSelectedStudentFile(inputId, infoContainerId, removeBtn, submitBtnId) {
  const input = document.getElementById(inputId);
  const infoContainer = document.getElementById(infoContainerId);
  const submitBtn = submitBtnId ? document.getElementById(submitBtnId) : null;
  if (input) input.value = '';
  if (infoContainer) infoContainer.innerHTML = '';
  if (removeBtn) removeBtn.classList.add('d-none');
  if (submitBtn) submitBtn.disabled = false;
}



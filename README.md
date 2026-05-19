# Hanilies Cakeshoppe

Hanilies Cakeshoppe is a Django-based cake ordering and event package booking system with a custom admin dashboard, real customer ordering flows, payment recording, order tracking, and a rule-based recommendation feature.

The current version is no longer a static prototype. It is now a functional local web system where customers can browse live products, place cake and package orders, submit payment details, and track actual transactions saved in the database.

## System Overview

The system supports two main customer transactions:

1. Cake ordering with customization options, payment method selection, and real order creation
2. Event package booking through a three-step flow with add-ons, package cake customization, event details, and payment submission

It also includes:

1. User registration, login, logout, and profile management
2. A custom admin panel for managing cakes, packages, orders, payments, and users
3. Order tracking for both cake and package orders
4. A rule-based personalized recommendation feature on the homepage

## Fully Functional Features

### Customer Side

1. Live homepage with personalized cake and package suggestions
2. Cake catalog with search and category filtering
3. Package catalog with search and package-type filtering
4. Real cake customization and ordering flow
5. Real three-step package booking flow
6. Cash on Delivery and GCash payment recording
7. Order tracking page with live order status and payment details
8. User profile page with real order count and total spending

### Admin Side

1. Custom admin dashboard
2. Cake management
3. Package management
4. Cake order monitoring and status updates
5. Package order monitoring and status updates
6. Payment verification management
7. User and role management

## Technology Stack

### Front-End

1. HTML5
2. CSS3
3. Bootstrap 5
4. JavaScript
5. Django Templates
6. Font Awesome

### Back-End

1. Python
2. Django 6.0.3
3. Django ORM
4. SQLite for local development
5. Django Session Framework
6. Django Authentication System
7. Django Messages Framework
8. Django Test Framework

### Supporting Libraries and Tools

1. Pillow for image handling
2. asgiref
3. sqlparse
4. tzdata

### Current Data and Logic Components

1. Cake model
2. CakeOrder model
3. CakeCustomization model
4. Package model
5. PackageOrder model
6. Payment model
7. UserProfile model
8. Rule-based recommendation engine using historical orders and best-selling items

## Tools Used

### Front-End Tools

1. HTML5 for page structure
2. CSS3 for styling
3. Bootstrap 5 for responsive layout and interface components
4. JavaScript for client-side interactions such as live totals and payment field toggling
5. Django Templates for rendering dynamic content from the backend

### Back-End Tools

1. Python for system logic and feature implementation
2. Django for routing, models, authentication, views, forms, and request handling
3. Django ORM for querying and updating database records
4. SQLite for local data storage
5. Django Sessions for the multi-step package booking draft flow
6. Django Authentication for account access and role-aware navigation
7. Django Test Framework for validating recommendation behavior and core functionality

## Methodology

### System Development Methodology

The project currently follows an iterative and incremental development methodology. The system began as a partially functional prototype with existing models and templates, then each major module was improved step by step until it became a working local web application.

The development process followed this pattern:

1. Assess the existing prototype and identify functional gaps
2. Replace static templates with live database-driven pages
3. Implement missing back-end logic for orders, payments, and tracking
4. Validate each flow locally through Django checks, tests, and browser-based verification
5. Improve the homepage and customer experience using real recommendation logic

### Recommendation Methodology

The recommendation feature uses a rule-based methodology, not machine learning.

The system analyzes:

1. Previous cake orders
2. Previous package bookings
3. Preferred cake category
4. Preferred flavor
5. Average spending range
6. Best-selling cakes
7. Best-selling packages

Based on these rules, the system computes match scores and recommends the most relevant cakes and event packages to the customer.

## From-To Changes

### From

The system originally had the correct basic models and page structure, but several customer-side pages were still static, hardcoded, or demo-only.

Before the update:

1. Homepage recommendations were placeholder content only
2. Cake and package catalogs were mostly static presentation pages
3. Cake ordering did not fully create real order records in the intended live flow
4. Package ordering was not fully implemented as a working multi-step transaction
5. Order tracking relied on demo-style content instead of live user orders
6. Profile statistics were hardcoded
7. Several customer interactions looked functional in the UI but were not yet complete end-to-end

### To

The system is now a fully functional local Django web application with real customer-side ordering, payment recording, tracking, profile summaries, and homepage recommendations.

After the update:

1. Homepage uses rule-based personalized recommendations
2. Cakes and packages are loaded from the database
3. Cake orders create real CakeOrder, CakeCustomization, and Payment records
4. Package bookings run through a real three-step transaction flow
5. Order tracking shows real cake and package orders per logged-in user
6. Profile page shows real order count and spending totals
7. Admin users can review new transactions through the custom admin dashboard

## Added

1. Real cake ordering flow
2. Real package booking flow
3. Session-based package draft handling
4. Payment record creation for cake and package orders
5. Cake customization record creation
6. Homepage rule-based recommendation engine
7. Homepage live best-seller and recommendation insights
8. Automated tests for homepage recommendation behavior
9. Live order tracking for customer orders
10. Live profile summaries

## Updated

1. Homepage content and recommendation logic
2. Cake catalog page
3. Package catalog page
4. Cake customization page
5. Package order page
6. Package cake customization page
7. Package payment page
8. Order tracking page
9. Profile page
10. Base navigation for role-aware admin access
11. Default image fallback behavior

## Removed

1. Hardcoded homepage recommendation cards
2. Hardcoded cake listing content
3. Hardcoded package listing content
4. Hardcoded tracking page data
5. Old demo-only ordering behavior that did not represent full real transactions

## Prerequisites

Before running the project locally, make sure the following are installed:

1. Python 3.13 or higher
2. pip
3. virtualenv or the built-in Python venv module
4. Git if you want to clone the repository

Optional but recommended:

1. VS Code
2. Python extension for VS Code

Notes:

1. The repository includes `runtime.txt` with `python-3.14.3` for deployment/runtime targeting
2. The current local development setup uses SQLite and does not require PostgreSQL

## Local Setup

### 1. Clone the project

```bash
git clone https://github.com/whiteheadbella/hanilies-cakeshoppe.git
cd hanilies-cakeshoppe
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply database migrations

```bash
python manage.py migrate
```

### 5. Create a superuser

```bash
python manage.py createsuperuser
```

### 6. Run the development server

```bash
python manage.py runserver
```

Open the system in your browser at:

```text
http://127.0.0.1:8000/
```

## Local Validation Commands

Check the Django project:

```bash
python manage.py check
```

Run tests:

```bash
python manage.py test hanilies.tests
```

## Current Recommendation Logic Summary

The current homepage recommendation system is rule-based.

It works by:

1. Checking a user's previous cake and package orders
2. Finding common categories and flavors
3. Measuring closeness to previous budget patterns
4. Comparing products against best-selling catalog items
5. Computing a match score
6. Displaying the top cake and package suggestions on the homepage

## Project Status

Current local status:

1. Functional customer ordering system
2. Functional admin dashboard
3. Functional payment recording and verification flow
4. Functional rule-based recommendation homepage
5. Functional automated tests for homepage recommendation behavior

## Important Note

This repository can be worked on locally without pushing changes to GitHub. The current system state described in this README reflects the live local implementation and not just the original prototype version.

Create a modern, responsive internal web application called Teclever Bid Intelligence Platform.

Purpose

The platform helps Teclever discover, analyze, prioritize, and track tender opportunities from multiple procurement portals using AI.

The application is intended for a small internal team of 5 users and therefore does not require roles, permissions, or an admin panel.

The focus should be on simplicity, speed, usability, and AI-assisted decision making.

⸻

Branding

* Placeholder for Teclever logo in the header.
* Clean enterprise SaaS design.
* Modern dashboard interface.
* Light theme.
* Professional blue and neutral color palette.
* Consistent spacing and typography.
* Fully responsive for Desktop, Tablet, and Mobile.

Design inspiration:

* Notion
* Linear
* Monday.com
* Jira

⸻

Authentication

Login Screen

Components:

* Teclever logo placeholder
* Email field
* Password field
* Remember Me checkbox
* Sign In button
* Forgot Password link

After successful login, redirect users to Dashboard.

⸻

Dashboard

Display summary cards:

* Total Bids
* New Bids
* Accepted Bids
* Rejected Bids
* High Priority Bids (Rating 4–5)
* Closing Soon

Display portal cards:

GEM

Government e-Marketplace

HAL

Hindustan Aeronautics Limited

ISRO

Indian Space Research Organisation

Selecting a portal opens its bid listing page.

⸻

Portal Bid Listing Page

Create a powerful data table.

Columns:

1. Bid ID
2. Open Date
3. Close Date
4. Ministry
5. Organization
6. Department
7. Location
8. Description
9. AI Rating (0–5)
10. AI Reasoning
11. Status
12. Action

Status values:

* New
* Accepted
* Rejected

Actions:

* Accept
* Reject

Default sorting:
Highest rated bids first.

⸻

Search & Filtering

Provide:

* Global Search
* Filter by Ministry
* Filter by Organization
* Filter by Department
* Filter by Rating
* Filter by Status
* Filter by Closing Date

Provide quick filters:

* High Priority (4–5)
* Moderate Priority (3)
* Low Priority (0–2)
* Closing This Week

⸻

AI Bid Intelligence Engine

The AI automatically processes opportunities from:

* GEM
* HAL
* ISRO

For every bid:

1. Extract all bid information.
2. Download linked tender documents.
3. Support:
    * PDF
    * DOCX
    * XLSX
    * ZIP attachments
4. Process all documents.
5. Generate embeddings and vectorized knowledge.
6. Evaluate bid relevance against Teclever capabilities.

⸻

Teclever Capability Matching

AI should evaluate bids against:

* UI/UX Design
* Product Design
* Website Design
* Web Development
* Software Development
* Enterprise Applications
* Digital Transformation
* Mobile Applications
* Branding
* Design Systems
* Data Visualization
* AI Solutions
* Automation
* Government Technology Projects

⸻

AI Rating System

Rate every bid:

Rating 0

No relevance

Rating 1

Very low relevance

Rating 2

Low relevance

Rating 3

Moderate opportunity

Rating 4

Strong opportunity

Rating 5

Excellent opportunity

⸻

AI Reasoning

For every bid, generate a concise explanation describing:

* Capability match
* Scope alignment
* Technical fit
* Timeline feasibility
* Potential risks
* Qualification likelihood

⸻

AI Summary Rules

If Rating = 3, 4, or 5

Generate:

Executive Summary

Scope Overview

Key Deliverables

Technical Requirements

Eligibility Criteria

Submission Requirements

Risks & Considerations

Why Teclever Should Pursue This

Include a business-focused recommendation explaining why this opportunity aligns with Teclever’s strengths.

⸻

If Rating = 0, 1, or 2

Generate:

Executive Summary

Why This Is Not a Strong Fit

Capability Gaps

Risks

Recommendation

Explain why Teclever may choose not to pursue this opportunity.

⸻

Bid Detail View

When a user clicks a bid row, open a detailed page or side panel.

Sections:

Bid Overview

Display:

* Bid ID
* Ministry
* Organization
* Department
* Dates
* Description
* Location

⸻

AI Evaluation

Display:

* AI Rating
* AI Reasoning
* Opportunity Score

⸻

AI Summary

Display the generated analysis.

⸻

Tender Documents

Display:

* Document Name
* File Type
* Preview
* Download

⸻

AI Document Assistant

Provide a chat interface.

Example questions:

* Summarize the tender.
* What are the mandatory qualifications?
* What deliverables are required?
* What technologies are requested?
* What is the project timeline?
* What are the submission requirements?

Responses should use retrieval from vectorized tender documents.

⸻

User Actions

Accept Button

When clicked:

* Mark bid as Accepted.
* Store username.
* Store timestamp.
* Update dashboard metrics.

Reject Button

When clicked:

* Mark bid as Rejected.
* Store username.
* Store timestamp.
* Update dashboard metrics.

Display confirmation modal before updating status.

⸻

Activity Tracking

Create an Activity Log page.

Display:

* User
* Bid ID
* Portal
* Action Taken
* Date & Time

Purpose:
Provide visibility into bid decisions without requiring user roles or administration.

⸻

Notifications

Display notifications for:

* New high-priority bids
* New rating 5 opportunities
* Closing deadlines approaching
* Newly processed tenders

⸻

Mobile Experience

Mobile should not use wide tables.

Use card-based bid layouts showing:

* Bid ID
* Organization
* Close Date
* Rating
* Status

Provide quick Accept and Reject buttons.

Tapping a card opens the full bid detail page.

⸻

Technical Architecture

Frontend:

* Next.js
* React
* Tailwind CSS

Backend:

* Node.js

Database:

* PostgreSQL

AI Layer:

* OpenAI-compatible LLM
* Vector Database
* RAG (Retrieval Augmented Generation)

Document Processing:

* PDF parsing
* DOCX parsing
* OCR support
* Embedding generation

The final product should feel like a professional AI-powered bid intelligence platform that helps Teclever quickly identify the most valuable government opportunities and make informed pursuit decisions with minimal effort.
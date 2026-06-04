export interface Bid {
  id: string;
  portalId: 'gem' | 'hal' | 'isro';
  openDate: string;
  closeDate: string;
  ministry: string;
  organization: string;
  department: string;
  location: string;
  description: string;
  aiRating: number;
  aiReasoning: string;
  status: 'new' | 'accepted' | 'rejected';
  aiSummary?: {
    executiveSummary: string;
    scopeOverview?: string;
    keyDeliverables?: string[];
    technicalRequirements?: string[];
    eligibilityCriteria?: string[];
    submissionRequirements?: string[];
    risksConsiderations?: string[];
    whyPursue?: string;
    whyNotFit?: string;
    capabilityGaps?: string[];
    recommendation?: string;
  };
  documents?: {
    name: string;
    type: string;
    url: string;
  }[];
}

export interface Activity {
  id: string;
  user: string;
  bidId: string;
  portal: string;
  action: 'accepted' | 'rejected';
  timestamp: string;
}

export const mockBids: Bid[] = [
  {
    id: 'GEM-2026-001',
    portalId: 'gem',
    openDate: '2026-05-15',
    closeDate: '2026-06-15',
    ministry: 'Ministry of Electronics & IT',
    organization: 'National Informatics Centre',
    department: 'Digital Services',
    location: 'New Delhi',
    description: 'Development of AI-powered citizen service portal with multilingual support, integrated payment gateway, and real-time analytics dashboard',
    aiRating: 5,
    aiReasoning: 'Perfect match for Teclever capabilities: requires UI/UX design, web development, AI solutions, and government technology expertise. High-value project with strong technical alignment.',
    status: 'new',
    aiSummary: {
      executiveSummary: 'High-value government portal development project requiring end-to-end digital transformation expertise, including AI integration and modern UI/UX design.',
      scopeOverview: 'Development of a comprehensive citizen service portal with AI chatbot, multilingual interface, payment integration, and analytics capabilities.',
      keyDeliverables: [
        'Responsive web portal with mobile apps',
        'AI-powered chatbot for citizen queries',
        'Multilingual support (Hindi, English, regional languages)',
        'Integrated payment gateway',
        'Real-time analytics dashboard',
        'Admin panel for content management'
      ],
      technicalRequirements: [
        'React/Next.js frontend',
        'Node.js backend',
        'AI/ML integration for chatbot',
        'PostgreSQL database',
        'Cloud deployment (AWS/Azure)',
        'WCAG 2.1 Level AA compliance'
      ],
      eligibilityCriteria: [
        'Minimum 5 years experience in government projects',
        'Portfolio of 3+ large-scale web applications',
        'AI/ML implementation experience',
        'ISO 27001 certification preferred'
      ],
      submissionRequirements: [
        'Technical proposal with architecture',
        'Project timeline (max 9 months)',
        'Team composition and CVs',
        'Financial proposal',
        'References from government clients'
      ],
      risksConsiderations: [
        'Tight 9-month timeline',
        'Complex compliance requirements',
        'Multiple stakeholder coordination'
      ],
      whyPursue: 'This project aligns perfectly with Teclever\'s core competencies in UI/UX design, web development, AI solutions, and government technology. It offers high visibility, strong portfolio value, and potential for long-term government partnerships.'
    },
    documents: [
      { name: 'RFP_Document.pdf', type: 'PDF', url: '#' },
      { name: 'Technical_Specifications.docx', type: 'DOCX', url: '#' },
      { name: 'Annexures.xlsx', type: 'XLSX', url: '#' }
    ]
  },
  {
    id: 'HAL-2026-042',
    portalId: 'hal',
    openDate: '2026-05-20',
    closeDate: '2026-06-25',
    ministry: 'Ministry of Defence',
    organization: 'Hindustan Aeronautics Limited',
    department: 'IT & Digital Systems',
    location: 'Bangalore',
    description: 'Enterprise resource planning system modernization with supply chain analytics, inventory management, and vendor portal',
    aiRating: 4,
    aiReasoning: 'Strong alignment with enterprise application development and data visualization capabilities. Complex project requiring digital transformation expertise.',
    status: 'new',
    aiSummary: {
      executiveSummary: 'Large-scale ERP modernization for defense manufacturing, requiring expertise in enterprise applications, data visualization, and supply chain management.',
      scopeOverview: 'Modernization of legacy ERP system with cloud migration, new analytics modules, and vendor collaboration portal.',
      keyDeliverables: [
        'Cloud-based ERP platform',
        'Supply chain analytics dashboard',
        'Inventory management system',
        'Vendor collaboration portal',
        'Mobile applications for field operations',
        'Integration with existing defense systems'
      ],
      technicalRequirements: [
        'Enterprise-grade architecture',
        'SAP/Oracle ERP expertise',
        'Advanced data visualization',
        'Secure cloud infrastructure',
        'Real-time analytics capabilities',
        'High-security compliance'
      ],
      eligibilityCriteria: [
        'Experience with defense/PSU clients',
        'ERP implementation track record',
        'Security clearance capability',
        'Minimum team size of 15 developers'
      ],
      submissionRequirements: [
        'Detailed technical proposal',
        '12-month implementation timeline',
        'Security and compliance documentation',
        'Change management plan',
        'Support and maintenance proposal'
      ],
      risksConsiderations: [
        'High security requirements',
        'Complex legacy system integration',
        'Strict compliance and audit requirements',
        'Long sales cycle typical for defense projects'
      ],
      whyPursue: 'Demonstrates Teclever\'s capability in enterprise applications and digital transformation. High-value contract with potential for ongoing maintenance and support work.'
    },
    documents: [
      { name: 'Tender_Notice.pdf', type: 'PDF', url: '#' },
      { name: 'Scope_of_Work.pdf', type: 'PDF', url: '#' }
    ]
  },
  {
    id: 'ISRO-2026-018',
    portalId: 'isro',
    openDate: '2026-05-25',
    closeDate: '2026-07-01',
    ministry: 'Department of Space',
    organization: 'Indian Space Research Organisation',
    department: 'Data Systems',
    location: 'Ahmedabad',
    description: 'Satellite data visualization platform for scientific research with 3D mapping, time-series analysis, and collaborative tools',
    aiRating: 5,
    aiReasoning: 'Exceptional fit for Teclever\'s data visualization and UI/UX expertise. Cutting-edge project with high technical prestige and innovation potential.',
    status: 'new',
    aiSummary: {
      executiveSummary: 'Prestigious satellite data visualization project combining advanced UI/UX design, 3D graphics, data visualization, and scientific computing.',
      scopeOverview: 'Development of an advanced platform for visualizing and analyzing satellite imagery and scientific data with collaborative research features.',
      keyDeliverables: [
        '3D interactive satellite data viewer',
        'Time-series analysis tools',
        'Collaborative research workspace',
        'Advanced filtering and search',
        'Data export and API access',
        'Mobile-responsive interface'
      ],
      technicalRequirements: [
        'WebGL/Three.js for 3D visualization',
        'High-performance data processing',
        'Advanced charting libraries',
        'Geospatial mapping capabilities',
        'Real-time collaboration features',
        'Large dataset handling'
      ],
      eligibilityCriteria: [
        'Portfolio of data visualization projects',
        'Experience with scientific/research applications',
        'Proven 3D graphics expertise',
        'Minimum 3 years relevant experience'
      ],
      submissionRequirations: [
        'Technical architecture proposal',
        'Interactive prototypes/demos',
        '10-month delivery timeline',
        'Team credentials',
        'Cost breakdown'
      ],
      risksConsiderations: [
        'Complex scientific requirements',
        'Performance optimization for large datasets',
        'Specialized domain knowledge needed'
      ],
      whyPursue: 'This is a high-prestige project showcasing Teclever\'s advanced capabilities in data visualization and UI/UX design. ISRO projects provide exceptional portfolio value and open doors to the scientific research sector.'
    },
    documents: [
      { name: 'Project_Brief.pdf', type: 'PDF', url: '#' },
      { name: 'Technical_Requirements.pdf', type: 'PDF', url: '#' }
    ]
  },
  {
    id: 'GEM-2026-089',
    portalId: 'gem',
    openDate: '2026-05-18',
    closeDate: '2026-06-20',
    ministry: 'Ministry of Health',
    organization: 'National Health Mission',
    department: 'Digital Health',
    location: 'Mumbai',
    description: 'Mobile health application for rural healthcare workers with offline sync, telemedicine, and patient record management',
    aiRating: 4,
    aiReasoning: 'Good match for mobile app development and healthcare technology. Requires strong UX focus for low-literacy users and robust offline capabilities.',
    status: 'accepted',
    aiSummary: {
      executiveSummary: 'Healthcare mobile app targeting rural workers with critical offline functionality and telemedicine integration.',
      scopeOverview: 'Development of a mobile-first healthcare platform designed for low-bandwidth environments with offline-first architecture.',
      keyDeliverables: [
        'Android and iOS mobile apps',
        'Offline-first architecture',
        'Telemedicine video consultation',
        'Patient record management',
        'Prescription and medicine tracking',
        'Multi-language support'
      ],
      technicalRequirements: [
        'React Native or Flutter',
        'Offline data synchronization',
        'WebRTC for video calls',
        'Secure healthcare data storage',
        'Low-bandwidth optimization',
        'Simple, icon-based UI for low-literacy users'
      ],
      eligibilityCriteria: [
        'Healthcare app development experience',
        'Mobile app portfolio',
        'HIPAA/healthcare compliance knowledge',
        'Rural/low-bandwidth app experience preferred'
      ],
      submissionRequirements: [
        'Technical proposal with offline strategy',
        '8-month timeline',
        'UX research plan',
        'Security and compliance documentation',
        'User training plan'
      ],
      risksConsiderations: [
        'Complex offline sync requirements',
        'Low-bandwidth environment challenges',
        'User adoption in rural areas',
        'Healthcare data security compliance'
      ],
      whyPursue: 'Demonstrates Teclever\'s mobile application expertise and social impact focus. Healthcare sector offers significant growth potential.'
    },
    documents: [
      { name: 'RFP.pdf', type: 'PDF', url: '#' }
    ]
  },
  {
    id: 'GEM-2026-134',
    portalId: 'gem',
    openDate: '2026-05-22',
    closeDate: '2026-06-18',
    ministry: 'Ministry of Education',
    organization: 'NCERT',
    department: 'Digital Learning',
    location: 'Delhi',
    description: 'Interactive e-learning platform with gamification, assessment tools, and teacher dashboard',
    aiRating: 3,
    aiReasoning: 'Moderate fit. Requires education domain expertise and complex gamification. Timeline is tight and scope may require significant R&D investment.',
    status: 'new',
    aiSummary: {
      executiveSummary: 'Education technology platform requiring gamification expertise and interactive learning tools.',
      scopeOverview: 'Development of a comprehensive e-learning platform with student engagement features and teacher management tools.',
      keyDeliverables: [
        'Student learning portal',
        'Gamified learning modules',
        'Assessment and quiz tools',
        'Teacher dashboard',
        'Progress tracking and analytics',
        'Parent portal'
      ],
      technicalRequirements: [
        'Interactive content delivery',
        'Gamification engine',
        'Video streaming',
        'Assessment automation',
        'Analytics and reporting',
        'Mobile responsive design'
      ],
      eligibilityCriteria: [
        'EdTech platform experience',
        'Gamification implementation',
        'Portfolio of learning applications'
      ],
      submissionRequirements: [
        'Technical proposal',
        '6-month timeline (tight)',
        'Content strategy',
        'User engagement plan'
      ],
      risksConsiderations: [
        'Tight 6-month timeline',
        'Gamification requires R&D',
        'Content creation not in core expertise',
        'Competitive edtech market'
      ],
      whyPursue: 'Could expand Teclever into education sector. Platform work aligns with web development strengths.'
    },
    documents: [
      { name: 'Tender_Document.pdf', type: 'PDF', url: '#' }
    ]
  },
  {
    id: 'HAL-2026-055',
    portalId: 'hal',
    openDate: '2026-05-12',
    closeDate: '2026-06-10',
    ministry: 'Ministry of Defence',
    organization: 'Hindustan Aeronautics Limited',
    department: 'Manufacturing',
    location: 'Nasik',
    description: 'IoT-based predictive maintenance system for aircraft manufacturing equipment with sensor integration',
    aiRating: 2,
    aiReasoning: 'Low fit. Requires specialized IoT hardware expertise and manufacturing domain knowledge outside Teclever\'s core competencies.',
    status: 'rejected',
    aiSummary: {
      executiveSummary: 'IoT and manufacturing-focused project requiring hardware integration and industrial domain expertise.',
      whyNotFit: 'This project is heavily focused on IoT hardware, sensor integration, and manufacturing processes which are outside Teclever\'s primary expertise in web/software development and design.',
      capabilityGaps: [
        'Limited IoT hardware experience',
        'No manufacturing domain expertise',
        'Lack of industrial sensor integration experience',
        'No predictive maintenance algorithm expertise'
      ],
      risksConsiderations: [
        'Requires significant hardware partnerships',
        'Manufacturing domain learning curve',
        'Specialized technical requirements',
        'High reliability and safety requirements'
      ],
      recommendation: 'Not recommended. Focus on projects aligned with Teclever\'s core strengths in UI/UX, web development, and digital transformation rather than hardware-centric IoT implementations.'
    },
    documents: []
  },
  {
    id: 'ISRO-2026-024',
    portalId: 'isro',
    openDate: '2026-05-28',
    closeDate: '2026-07-05',
    ministry: 'Department of Space',
    organization: 'Indian Space Research Organisation',
    department: 'Mission Control',
    location: 'Bangalore',
    description: 'Mission control dashboard redesign with real-time telemetry visualization and alert management',
    aiRating: 5,
    aiReasoning: 'Excellent opportunity showcasing Teclever\'s UI/UX design and real-time data visualization expertise for a prestigious organization.',
    status: 'new',
    aiSummary: {
      executiveSummary: 'High-impact UI/UX redesign project for ISRO mission control systems, requiring exceptional real-time visualization and critical system design.',
      scopeOverview: 'Complete redesign of mission control interface with focus on usability, real-time data display, and critical alert management.',
      keyDeliverables: [
        'Redesigned mission control UI',
        'Real-time telemetry dashboards',
        'Alert and notification system',
        'Historical data analysis tools',
        'Customizable operator views',
        'Dark mode optimization for control rooms'
      ],
      technicalRequirements: [
        'High-performance real-time rendering',
        'WebSocket for live data',
        'Advanced charting and visualization',
        'Accessibility for 24/7 operations',
        'Responsive design for multiple displays',
        'Fail-safe error handling'
      ],
      eligibilityCriteria: [
        'Portfolio of mission-critical UI/UX work',
        'Real-time dashboard experience',
        'Design system development capability',
        'Proven track record with large organizations'
      ],
      submissionRequirements: [
        'UI/UX proposal with mockups',
        '7-month timeline',
        'Usability testing plan',
        'Design system documentation',
        'Accessibility compliance proof'
      ],
      risksConsiderations: [
        'Mission-critical nature requires zero-error tolerance',
        'Complex user workflows',
        'Security clearance may be required'
      ],
      whyPursue: 'Exceptional portfolio piece demonstrating Teclever\'s ability to handle mission-critical, high-stakes design work for India\'s premier space organization. Perfect alignment with UI/UX and data visualization strengths.'
    },
    documents: [
      { name: 'Design_Brief.pdf', type: 'PDF', url: '#' },
      { name: 'Current_System_Overview.pdf', type: 'PDF', url: '#' }
    ]
  },
  {
    id: 'GEM-2026-201',
    portalId: 'gem',
    openDate: '2026-05-30',
    closeDate: '2026-06-28',
    ministry: 'Ministry of MSME',
    organization: 'MSME Development Institute',
    department: 'Digital Services',
    location: 'Hyderabad',
    description: 'MSME vendor onboarding portal with document verification, compliance tracking, and marketplace integration',
    aiRating: 4,
    aiReasoning: 'Strong fit for Teclever\'s web development and enterprise application expertise. Good scope for design system implementation.',
    status: 'new',
    aiSummary: {
      executiveSummary: 'Government marketplace platform requiring robust workflow management, document handling, and integration capabilities.',
      scopeOverview: 'Development of a comprehensive vendor onboarding and management platform for MSME businesses.',
      keyDeliverables: [
        'Vendor registration and KYC portal',
        'Document upload and verification system',
        'Compliance tracking dashboard',
        'Marketplace integration APIs',
        'Admin panel for verification team',
        'Automated email notifications'
      ],
      technicalRequirements: [
        'Secure document storage',
        'Multi-step form workflows',
        'API integration capabilities',
        'Role-based access control',
        'Audit trail and logging',
        'Mobile-responsive design'
      ],
      eligibilityCriteria: [
        'Government portal development experience',
        'Document management system expertise',
        'API integration track record',
        'Portfolio of enterprise applications'
      ],
      submissionRequirements: [
        'Technical architecture proposal',
        '8-month implementation plan',
        'Security and compliance documentation',
        'Team composition',
        'Pricing breakdown'
      ],
      risksConsiderations: [
        'Complex verification workflows',
        'Integration with multiple government systems',
        'High data security requirements'
      ],
      whyPursue: 'Aligns well with enterprise application development strengths. MSME sector focus offers potential for related projects and long-term partnerships.'
    },
    documents: [
      { name: 'Project_Requirements.pdf', type: 'PDF', url: '#' }
    ]
  }
];

export const mockActivities: Activity[] = [
  {
    id: '1',
    user: 'Rajesh Kumar',
    bidId: 'GEM-2026-089',
    portal: 'GEM',
    action: 'accepted',
    timestamp: '2026-06-01T14:30:00Z'
  },
  {
    id: '2',
    user: 'Priya Sharma',
    bidId: 'HAL-2026-055',
    portal: 'HAL',
    action: 'rejected',
    timestamp: '2026-06-01T11:15:00Z'
  },
  {
    id: '3',
    user: 'Amit Patel',
    bidId: 'GEM-2026-001',
    portal: 'GEM',
    action: 'accepted',
    timestamp: '2026-05-31T16:45:00Z'
  }
];

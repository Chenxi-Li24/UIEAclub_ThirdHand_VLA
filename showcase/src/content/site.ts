/**
 * All page copy in one place.
 * -----------------------------------------------------------------------------
 * Every section carries one title and at most two short supporting sentences.
 * Nothing here claims a performance figure, a test result, a partner, or a
 * safety property that the project documentation does not support.
 */

export const site = {
  name: 'ThirdHand',
  owner: 'UIEA Club',
  year: 2026,
} as const;

export const nav = [
  { id: 'actions', label: 'Actions' },
  { id: 'demos', label: 'Demos' },
  { id: 'lab', label: 'Built in the Lab' },
  { id: 'platform', label: 'Platform' },
  { id: 'team', label: 'Team' },
] as const;

export const controlEntry = {
  label: 'Open Control',
  href: 'https://staging.uiea-thirdhand.com/login',
} as const;

export const hero = {
  eyebrow: 'UIEA Club / Embodied intelligence project',
  headlineLines: ['Your intelligent', 'third hand.'],
  support:
    'ThirdHand is a robotic-arm assistant that perceives its surroundings, understands tasks and helps handle objects in real-world desktop environments.',
  cta: { label: 'See what it can do', heroLabel: 'View project introduction', href: '#actions' },
  demoCta: {
    label: 'Watch demo videos',
    href: '#demos',
  },
  scrollHint: 'Scroll',
} as const;

export const actions = {
  chapter: '01',
  name: 'Actions',
  headline: 'See. Plan. Act.',
  support:
    'ThirdHand connects perception, task understanding and controlled movement—turning a user’s intention into physical assistance.',
  acts: [
    {
      id: 'see',
      index: '01',
      label: 'Perceive the environment',
      copy: 'Vision identifies the workspace, locates target objects and understands the context around them.',
    },
    {
      id: 'move',
      index: '02',
      label: 'Plan and move',
      copy: 'The system interprets the task and plans a controlled path through the physical environment.',
    },
    {
      id: 'grasp',
      index: '03',
      label: 'Grasp and assist',
      copy: 'ThirdHand can approach, hold and move everyday objects—supporting tasks such as picking up, passing and organizing items.',
    },
  ],
} as const;

export const demos = {
  chapter: '02',
  name: 'Video Demos',
  headline: 'Watch ThirdHand work.',
  support:
    'Three recorded demonstrations show visual grasping, voice-controlled object pickup and person-following behavior on the working robotic platform.',
  items: [
    {
      index: '01',
      tag: 'Visual targeting · Controlled grasp',
      title: 'Bottle pickup',
      description: 'ThirdHand locates a bottle, approaches it and completes the grasp.',
    },
    {
      index: '02',
      tag: 'Voice understanding · Command execution',
      title: 'Voice-controlled object pickup',
      description: 'A spoken instruction is interpreted and carried through to physical action.',
    },
    {
      index: '03',
      tag: 'Target detection · Real-time following',
      title: 'Person-following mode',
      description: 'The dummy mode tracks a person and follows their movement in real time.',
    },
  ],
} as const;

export const lab = {
  chapter: '03',
  name: 'Built in the Lab',
  headline: 'Built as one complete system.',
  support:
    'Robot control, visual perception, object localization, grasp execution and software interaction have been integrated into a working physical platform. From CAD and printed prototypes to intelligent interfaces, every layer is developed and refined by the UIEA team.',
} as const;

export const platform = {
  chapter: '04',
  name: 'Platform',
  headline: 'Modular by design. Ready to grow.',
  support:
    'Reusable robotic capabilities and intelligent interaction allow ThirdHand to learn new tasks without rebuilding the entire system for every new scenario.',
  flow: [
    { index: '01', label: 'Perceive', detail: 'Environment and objects' },
    { index: '02', label: 'Understand', detail: 'Task and context' },
    { index: '03', label: 'Plan', detail: 'Motion and action' },
    { index: '04', label: 'Act', detail: 'Physical assistance' },
  ],
  principles: [
    {
      label: 'Accessible',
      copy: 'Designed for natural use beyond specialist programming and complex deployment.',
    },
    {
      label: 'Modular',
      copy: 'Perception, planning, control and interaction capabilities can evolve independently.',
    },
    {
      label: 'Extensible',
      copy: 'New skills can be added as the platform moves into new tasks and environments.',
    },
  ],
  vision:
    'Starting with desktop assistance, ThirdHand can grow into applications across smart homes, human–robot collaboration and flexible manufacturing.',
} as const;

export const team = {
  chapter: '05',
  name: 'Team',
  headline: 'Built by UIEA.',
  support:
    'A multidisciplinary student team integrating mechanical design, perception, control, software and human–robot interaction into one working system.',
} as const;

export const footer = {
  statement: 'Building an accessible platform for real-world human–robot collaboration.',
  rights: `© ${site.year} UIEA Club · ThirdHand`,
} as const;

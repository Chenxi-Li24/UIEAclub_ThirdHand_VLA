/**
 * Central media registry.
 * -----------------------------------------------------------------------------
 * Every image and video the site loads is declared here, so replacing media
 * later is a change to this file plus tracked ready-to-use media files. Nothing outside
 * this file hard-codes a path.
 *
 * Alt text and captions stay brand-neutral: markings that happen to be visible
 * in a photograph are left alone, but the written copy never names a
 * manufacturer or a commercial product.
 */

export type MediaKind = 'photograph' | 'interface' | 'cad';

export interface MediaSource {
  src: string;
  /** Smaller variants for `srcSet`. */
  srcSet?: string;
  sizes?: string;
  width: number;
  height: number;
  alt: string;
  kind?: MediaKind;
  caption?: string;
  /** `object-position` when the subject sits off-centre. */
  focus?: string;
  /**
   * Optional JPEG set for clients without WebP. When present the image renders
   * as a `<picture>`; the WebP above stays the preferred source.
   */
  fallback?: { src: string; srcSet?: string; type: string };
}

export interface VideoSource {
  src: string;
  type: string;
  poster: MediaSource;
  width: number;
  height: number;
  /** Describes the clip for people who cannot see it. */
  label: string;
  /** Only set where the last frame meets the first cleanly. */
  loop?: boolean;
}

export interface DemoVideoSource {
  src: string;
  type: 'video/mp4';
  label: string;
}

/* -------------------------------------------------------------------------- */
/* Hero                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Swap this for a `heroVideo` entry once a silent 16:9 loop exists — HeroMedia
 * already accepts one and falls back to this still as its poster.
 */
export const heroMedia: MediaSource = {
  src: '/media/hero-robot.webp',
  srcSet:
    '/media/hero-robot-1000.webp 1000w, /media/hero-robot-1600.webp 1600w, /media/hero-robot.webp 2400w',
  sizes: '100vw',
  width: 2400,
  height: 1800,
  alt: 'Robotic arm on a workbench with a camera above its gripper, beside a printed visual calibration board.',
  kind: 'photograph',
};

/* -------------------------------------------------------------------------- */
/* Actions                                                                     */
/* -------------------------------------------------------------------------- */

/** 01 — See. Live software output, with the detection view alongside it. */
export const visionVideo: VideoSource = {
  src: '/media/vision-software.mp4',
  type: 'video/mp4',
  width: 1180,
  height: 708,
  loop: true,
  label:
    'Screen recording of the control software: a live model of the arm on the left, the camera view with detected objects outlined on the right.',
  poster: {
    src: '/media/vision-software-poster.webp',
    width: 1180,
    height: 708,
    alt: 'Control software showing a model of the arm beside a wide-angle camera view with detected objects outlined.',
    kind: 'interface',
  },
};

export const visionStill: MediaSource = {
  src: '/media/vision-detection.webp',
  srcSet: '/media/vision-detection-640.webp 640w, /media/vision-detection.webp 1000w',
  sizes: '(min-width: 62rem) 17rem, 40vw',
  width: 1000,
  height: 1146,
  alt: 'Wide-angle camera view of a workspace with object outlines drawn around a bottle, the calibration board and people.',
  kind: 'interface',
};

/**
 * 02 — Move. The arm working, from the original recording. The clip does not
 * return to its opening pose, so it is not looped: it plays from the start each
 * time the act is entered and holds on its last frame.
 */
export const motionVideo: VideoSource = {
  src: '/media/motion-robot.mp4',
  type: 'video/mp4',
  width: 1280,
  height: 1002,
  loop: false,
  label: 'The robotic arm moving through a planned path above a workbench in the project lab.',
  poster: {
    src: '/media/motion-robot-poster.webp',
    width: 1280,
    height: 1002,
    alt: 'The robotic arm extended above a workbench in the project lab, its camera head raised.',
    kind: 'photograph',
  },
};

/** 03 — Grasp. The task itself, with the calibration photograph supporting it. */
export const graspVideo: VideoSource = {
  src: '/media/grasp-task.mp4',
  type: 'video/mp4',
  width: 480,
  height: 360,
  loop: true,
  label: 'The arm approaching a bottle on a desk, closing its gripper and lifting it.',
  poster: {
    src: '/media/grasp-task-poster.webp',
    width: 480,
    height: 360,
    alt: 'The arm reaching towards a bottle standing on a desk.',
    kind: 'photograph',
  },
};

export const graspSupport: MediaSource = {
  src: '/media/arm-calibration.webp',
  srcSet: '/media/arm-calibration-900.webp 900w, /media/arm-calibration.webp 1400w',
  sizes: '(min-width: 62rem) 11rem, 58vw',
  width: 1400,
  height: 1050,
  alt: 'A student holding a printed calibration board in front of the camera mounted above the gripper.',
  kind: 'photograph',
};

/* -------------------------------------------------------------------------- */
/* Full demonstrations                                                         */
/* -------------------------------------------------------------------------- */

export const demoVideos: DemoVideoSource[] = [
  {
    src: '/media/demos/01-bottle-pickup.mp4',
    type: 'video/mp4',
    label: 'ThirdHand robotic arm locating and picking up a bottle.',
  },
  {
    src: '/media/demos/02-voice-pickup.mp4',
    type: 'video/mp4',
    label: 'ThirdHand robotic arm picking up an object in response to a voice command.',
  },
  {
    src: '/media/demos/03-dummy-follow.mp4',
    type: 'video/mp4',
    label: 'ThirdHand robotic arm following a moving person in dummy mode.',
  },
];

/* -------------------------------------------------------------------------- */
/* Built in the Lab                                                            */
/* -------------------------------------------------------------------------- */

/**
 * The gallery opens with one panoramic CAD view at full content width. It keeps
 * its own 1749:562 ratio and is never cropped into a card — the assembly runs
 * from one end of the frame to the other and both ends matter.
 */
export const labPanorama: MediaSource = {
  src: '/media/lab-cad-arm.webp',
  srcSet:
    '/media/lab-cad-arm-800.webp 800w, /media/lab-cad-arm-1200.webp 1200w, /media/lab-cad-arm.webp 1749w',
  sizes:
    '(min-width: 88rem) 84rem, (min-width: 48rem) calc(100vw - 4rem), calc(100vw - 2.5rem)',
  width: 1749,
  height: 562,
  alt: 'CAD view of a multi-joint arm linkage with a hand assembly at one end.',
  kind: 'cad',
  caption: 'Mechanical design',
};

/**
 * Ten equal 4:5 cards. The card is the fixed shape; each photograph is
 * contained inside it complete, so nothing is cut off and nothing is stretched.
 */
export const labCards: MediaSource[] = [
  {
    src: '/media/lab-additive-print.webp',
    srcSet: '/media/lab-additive-print-720.webp 720w, /media/lab-additive-print.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'An open-frame desktop 3D printer part-way through printing a white lattice component, on a workbench in the project lab.',
    kind: 'photograph',
    caption: 'Rapid prototyping',
  },
  {
    src: '/media/lab-end-effector.webp',
    srcSet: '/media/lab-end-effector-720.webp 720w, /media/lab-end-effector.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'A printed two-finger end effector with ribbed compliant fingers, mounted on a motor and standing on a workbench.',
    kind: 'photograph',
    caption: 'End-effector prototype',
  },
  {
    src: '/media/lab-cad-assembly.webp',
    srcSet: '/media/lab-cad-assembly-560.webp 560w, /media/lab-cad-assembly.webp 800w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 800,
    height: 1033,
    alt: 'CAD view of a gripper assembly mounted on the wrist of an arm, with the drive mechanism visible.',
    kind: 'cad',
    caption: 'System assembly',
  },
  {
    src: '/media/lab-print-farm.webp',
    srcSet: '/media/lab-print-farm-720.webp 720w, /media/lab-print-farm.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'An enclosed 3D printer with a multi-material feeder on a workbench in the lab.',
    kind: 'photograph',
    caption: 'Additive manufacturing',
  },
  {
    src: '/media/lab-immersive.webp',
    srcSet: '/media/lab-immersive-720.webp 720w, /media/lab-immersive.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'A virtual-reality headset and controller on a stand beside a printed skeletal hand.',
    kind: 'photograph',
    caption: 'Immersive interface research',
  },
  {
    src: '/media/lab-arm-prototype.webp',
    srcSet: '/media/lab-arm-prototype-720.webp 720w, /media/lab-arm-prototype.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'Orange and black 3D-printed arm prototype with a two-finger gripper, joint housing and exposed cable on a laboratory table.',
    kind: 'photograph',
    caption: 'ARM PROTOTYPE',
  },
  {
    src: '/media/lab-large-robot-arm.webp',
    srcSet:
      '/media/lab-large-robot-arm-720.webp 720w, /media/lab-large-robot-arm.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'Large white multi-joint robotic arm mounted on a wheeled base in an open laboratory workspace.',
    kind: 'photograph',
    caption: 'LARGE-SCALE ROBOTIC ARM',
  },
  {
    src: '/media/lab-robot-arm-controller.webp',
    srcSet:
      '/media/lab-robot-arm-controller-720.webp 720w, /media/lab-robot-arm-controller.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'Handheld articulated controller prototype with white 3D-printed links, black motors and exposed red, white and black wiring.',
    kind: 'photograph',
    caption: 'ROBOT ARM CONTROLLER',
  },
  {
    src: '/media/lab-robotic-arm.webp',
    srcSet: '/media/lab-robotic-arm-720.webp 720w, /media/lab-robotic-arm.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'Wearable robotic arm prototype strapped to a person, with a white articulated hand, motors and exposed multicolour wiring.',
    kind: 'photograph',
    caption: 'ROBOTIC ARM',
  },
  {
    src: '/media/lab-motor-assembly.webp',
    srcSet:
      '/media/lab-motor-assembly-720.webp 720w, /media/lab-motor-assembly.webp 1200w',
    sizes:
      '(min-width: 88rem) 27rem, (min-width: 62rem) calc((100vw - 7rem) / 3), calc((100vw - 5.5rem) / 2)',
    width: 1200,
    height: 1600,
    alt: 'Compact linear motor assembly with an aluminium frame, guide rods, lead screw and bundled control wires on a laboratory table.',
    kind: 'photograph',
    caption: 'MOTOR ASSEMBLY',
  },
];

/* -------------------------------------------------------------------------- */
/* Team                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * The complete frame at its natural 4:3. Everyone in the room, both people
 * joining on the monitors, and the prototypes on the bench are part of what the
 * picture says, so it is never cropped — at any width it is shown whole.
 */
export const teamPhoto: MediaSource = {
  src: '/media/team-lab.webp',
  srcSet:
    '/media/team-lab-900.webp 900w, /media/team-lab-1400.webp 1400w, /media/team-lab.webp 2000w',
  sizes:
    '(min-width: 88rem) 84rem, (min-width: 48rem) calc(100vw - 4rem), calc(100vw - 2.5rem)',
  width: 2000,
  height: 1500,
  alt: 'UIEA student project team gathered in the laboratory behind robotic prototypes, cameras and interface equipment, with two remote members joining on monitors.',
  kind: 'photograph',
  fallback: {
    src: '/media/team-lab.jpg',
    srcSet: '/media/team-lab-900.jpg 900w, /media/team-lab.jpg 1400w',
    type: 'image/jpeg',
  },
};

/* -------------------------------------------------------------------------- */
/* Identity                                                                    */
/* -------------------------------------------------------------------------- */

/** Proportions are preserved exactly from the supplied lockup. */
export const brandMarks = {
  wordmark: {
    src: '/media/thirdhand-wordmark.png',
    width: 712,
    height: 220,
    alt: 'UIEA Club ThirdHand',
  },
  lockup: {
    src: '/media/thirdhand-logo.png',
    width: 1342,
    height: 826,
    alt: 'UIEA Club ThirdHand — line-drawn robotic arm lockup',
  },
} as const;

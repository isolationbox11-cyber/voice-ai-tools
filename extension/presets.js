/* presets.js - Voice AI Tools Training Presets */

const TRAINING_PRESETS = [
  {
    id: 'calm',
    label: 'Calm & Relaxed',
    moodImage: '😌',
    moodBg: 'linear-gradient(135deg, #4CC9F0, #7B2FBE)',
    uiHint: 'Speak naturally, like you\'re talking to a close friend',
    text: `Hi there! I'm really glad we could connect today. I've been looking forward to this conversation, and I want you to know that I'm here to listen and share openly. There's something comforting about being able to just be ourselves, isn't there? I find that when we're relaxed and authentic, the best conversations happen naturally. So tell me, how has your day been going? What's been on your mind lately? I'm genuinely curious to hear what you've been experiencing and what matters to you right now. Sometimes just taking a moment to breathe and be present can make all the difference in how we connect with others. I appreciate you taking the time to be here with me today.`
  },
  {
    id: 'rant',
    label: 'Passionate Rant',
    moodImage: '😤',
    moodBg: 'linear-gradient(135deg, #F72585, #7B2FBE)',
    uiHint: 'Let your frustration out! Be energetic and expressive',
    text: `Are you kidding me right now?! I cannot believe what just happened! This is absolutely ridiculous and I'm not going to stand for it anymore. I've been putting up with this nonsense for way too long and I'm completely fed up! The sheer audacity of some people just blows my mind! Do they think I'm stupid? Do they think I won't notice what they're trying to pull? Because let me tell you something - I see EVERYTHING! I'm tired of being polite and patient when clearly that gets me nowhere! It's time to speak up and make some noise about this! This needs to stop right now and I'm not backing down until something changes! I'm so done with all the games and the excuses and the complete lack of respect! ENOUGH IS ENOUGH!`
  },
  {
    id: 'curious',
    label: 'Curious & Inquisitive',
    moodImage: '🤔',
    moodBg: 'linear-gradient(135deg, #06D6A0, #7B2FBE)',
    uiHint: 'Be genuinely curious, ask questions, explore ideas',
    text: `That's really interesting... I wonder what would happen if we looked at this from a completely different angle? Have you ever considered how this might connect to other things we've been discussing? It's fascinating how patterns emerge when you start connecting the dots. What do you think would be the most unexpected outcome here? I'm genuinely curious about your perspective on this. Sometimes the most brilliant insights come from asking the questions nobody else is asking. What if we tried something completely unconventional? What would that look like? I'd love to explore the possibilities with you. There's something about this that feels like it could lead somewhere really remarkable if we just dig a little deeper. What's your gut telling you about all of this?`
  },
  {
    id: 'singing',
    label: 'Singing & Melodic',
    moodImage: '🎤',
    moodBg: 'linear-gradient(135deg, #FF6B6B, #FFB800)',
    uiHint: 'Sing with emotion! Be expressive and melodic',
    text: `🎵 Oh what a beautiful morning! 🎵 The sun is shining bright and I feel so alive! 🎵 There's music in the air and joy in my heart! 🎵 La la la la la, this is where I want to be! 🎵 Singing makes everything better, don't you think? 🎵 When I raise my voice in song, all my worries fade away! 🎵 Tra la la la, what a wonderful day! 🎵 I could sing forever and ever! 🎵 Music is the language of the soul! 🎵 Do re mi fa so la ti do! 🎵 What a perfect moment this is! 🎵`
  }
];

// Export for use in popup.js
if (typeof window !== 'undefined') {
  window.TRAINING_PRESETS = TRAINING_PRESETS;
}

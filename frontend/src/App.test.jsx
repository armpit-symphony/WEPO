import React from 'react';

// Simple test app to verify React is working
const TestApp = () => {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      backgroundColor: '#1a1a2e',
      color: 'white',
      fontFamily: 'Arial, sans-serif'
    }}>
      <div style={{ textAlign: 'center' }}>
        <h1>🔥 WEPO WALLET TEST</h1>
        <p>React is working properly!</p>
        <p>Release-gated features default to disabled</p>
        <div style={{ 
          marginTop: '20px', 
          padding: '10px', 
          backgroundColor: '#16213e', 
          borderRadius: '8px' 
        }}>
          <p>Frontend harness: rendered</p>
          <p>Backend integration: tested separately</p>
          <p>Optional features: explicit build gates required</p>
          <p>Mainnet readiness: no claim from this harness</p>
        </div>
      </div>
    </div>
  );
};

test('frontend harness is defined', () => expect(TestApp).toBeDefined());

export default TestApp;

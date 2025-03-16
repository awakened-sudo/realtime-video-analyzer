/* 
     _____  .__  ____   ___.__    .___            
    /  _  \ |__| \   \ /   |__| __| _/____  ____  
   /  /_\  \|  |  \   Y   /|  |/ __ _/ __ \/  _ \ 
  /    |    |  |   \     / |  / /_/ \  ___(  <_> )
  \____|__  |__|    \___/  |__\____ |\___  \____/ 
          \/                       \/    \/       
                created by rUv
*/

const video = document.getElementById('video');
const formattedMarkdownDiv = document.getElementById('formattedMarkdown');
const toggleSettingsButton = document.getElementById('toggleSettings');
const settingsPanel = document.querySelector('.settings-panel');
const saveSettingsButton = document.getElementById('saveSettings');
const startCaptureButton = document.getElementById('startCapture');
const stopCaptureButton = document.getElementById('stopCapture');

const defaultPrompts = {
    general: "Analyze this frame for text, objects, and overall scene context.",
    weapon: "Focus specifically on detecting weapons or weapon-like objects in this frame. Look for: 1) Firearms (guns, rifles, pistols) including toys and replicas 2) Knives, blades, or sharp objects 3) Explosive devices or replicas 4) Improvised weapons or threatening objects. IMPORTANT: If you see ANY object that resembles a weapon (even toys, replicas, or props), explicitly write 'WEAPON DETECTED:' followed by the type and whether it appears to be real or a toy/replica. If absolutely nothing weapon-like is visible, state 'NO WEAPONS DETECTED' at the beginning of your response.",
    handsign: "Focus specifically on detecting peace signs (✌️) in this frame. Look for: 1) V-shaped hand gesture with index and middle fingers 2) Palm facing camera 3) Clear visibility of the gesture. IMPORTANT: Only if you clearly see a peace sign gesture, explicitly write 'PEACE SIGN DETECTED' in your response and include the ✌️ emoji. If no peace sign is visible, clearly state 'NO PEACE SIGN DETECTED' at the beginning of your response. Describe the confidence level and positioning of any detected peace sign."
};

let currentPromptMode = 'general';
let customPrompt = defaultPrompts.general;
let captureInterval = null;
let refreshRate = 1;  // Updated to match HTML default
let activeStream = null;
let isProcessing = false; // Flag to track if processing is in progress
let isCapturing = false;

function logMessage(message) {
    const p = document.createElement('p');
    p.textContent = message;
    formattedMarkdownDiv.appendChild(p);
    formattedMarkdownDiv.scrollTop = formattedMarkdownDiv.scrollHeight; // Scroll to bottom
}

async function startWebcamStream() {
    activeStream = await navigator.mediaDevices.getUserMedia({ video: true });
    logMessage("Webcam stream started.");
    video.srcObject = activeStream;
}

async function startScreenShare() {
    activeStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
    logMessage("Screen share started.");
    video.srcObject = activeStream;
}

async function startApplicationShare() {
    activeStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
            cursor: "always",
            displaySurface: "application"
        }
    });
    logMessage("Application share started.");
    video.srcObject = activeStream;
}

async function handleStreamSelection(event) {
    if (isProcessing) {
        event.stopImmediatePropagation(); // Stop event propagation immediately
        return; // Terminate the function
    }
    isProcessing = true; // Set the flag to indicate processing is in progress

    // Remove active class from all buttons
    document.querySelectorAll('.btn-group-toggle .btn').forEach(btn => btn.classList.remove('active'));

    // Add active class to the clicked button
    event.target.closest('.btn').classList.add('active');

    const selectedButton = event.target.closest('.btn').querySelector('input');
    if (!selectedButton) {
        console.error('No input element found inside the clicked button.');
        isProcessing = false; // Reset the flag
        return;
    }

    const selectedButtonId = selectedButton.id;
    if (activeStream) {
        // Stop the previous stream
        let tracks = activeStream.getTracks();
        tracks.forEach(track => track.stop());
        activeStream = null;
    }

    if (selectedButtonId === 'shareWebcam') {
        await startWebcamStream();
    } else if (selectedButtonId === 'shareScreen') {
        await startScreenShare();
    } else if (selectedButtonId === 'shareApplication') {
        await startApplicationShare();
    }

    isProcessing = false; // Reset the flag after processing is complete
}

// Event delegation for stream selection buttons
document.body.addEventListener('click', (event) => {
    if (event.target.closest('.btn-group-toggle .btn')) {
        handleStreamSelection(event);
    }
});

// Initialize button states
document.addEventListener('DOMContentLoaded', () => {
    stopCaptureButton.classList.remove('active');
    startCaptureButton.classList.remove('capturing');
});

// Start Capture
startCaptureButton.addEventListener('click', async () => {
    if (isProcessing || isCapturing) {
        return;
    }
    
    isProcessing = true;
    isCapturing = true;
    
    // Update button states
    startCaptureButton.classList.add('capturing');
    stopCaptureButton.classList.add('active');
    
    try {
        // Start capture process
        await captureFrame();
        if (isCapturing) { // Check if we're still meant to be capturing
            captureInterval = setInterval(captureFrame, refreshRate * 1000);
        }
        logMessage("Capture started.");
    } catch (error) {
        console.error("Error starting capture:", error);
        logMessage("Error starting capture.");
        stopCapture();
    }
    
    isProcessing = false;
});

// Stop Capture
stopCaptureButton.addEventListener('click', () => {
    if (!isCapturing) {
        return;
    }
    stopCapture();
});

// Helper function to stop capture
function stopCapture() {
    isCapturing = false;
    
    // Clear the capture interval
    if (captureInterval) {
        clearInterval(captureInterval);
        captureInterval = null;
    }
    
    // Reset button states
    startCaptureButton.classList.remove('capturing');
    stopCaptureButton.classList.remove('active');
    
    logMessage("Capture stopped.");
}

// Capture frame function
async function captureFrame() {
    if (!isCapturing) {
        return;
    }
    
    try {
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/jpeg');
        
        const requestData = {
            image: dataUrl,
            prompt: customPrompt
        };

        const apiUrl = window.location.origin.includes('5000') 
            ? '/process_frame'
            : 'http://127.0.0.1:5000/process_frame';

        console.log("Sending request to:", apiUrl);
        
        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(requestData)
        });
        
        console.log("Response status:", response.status);
        console.log("Response headers:", response.headers);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error("Error response:", errorText);
            throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
        }
        
        const contentType = response.headers.get("content-type");
        console.log("Content-Type:", contentType);
        
        if (!contentType || !contentType.includes("application/json")) {
            throw new TypeError("Response was not JSON");
        }
        
        const data = await response.json();
        console.log("Received data:", data);
        if (data && data.response) {
            formattedMarkdownDiv.textContent = data.response;
            formattedMarkdownDiv.scrollTop = formattedMarkdownDiv.scrollHeight;
        } else {
            throw new Error('Invalid response format');
        }
    } catch (error) {
        console.error('Error:', error);
        logMessage(`Error: ${error.message}`);
        formattedMarkdownDiv.textContent = `Error: ${error.message}`;
    }
}

// Toggle settings panel
toggleSettingsButton.addEventListener('click', () => {
    const isVisible = settingsPanel.style.display === 'block';
    settingsPanel.style.display = isVisible ? 'none' : 'block';
    toggleSettingsButton.classList.toggle('active');
    logMessage("");
});

// Handle prompt option changes
document.querySelectorAll('input[name="promptOption"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        currentPromptMode = e.target.value;
        const customPromptText = document.getElementById('customPrompt').value.trim();
        
        // Only update the textarea if it's empty or contains a default prompt
        if (!customPromptText || Object.values(defaultPrompts).includes(customPromptText)) {
            document.getElementById('customPrompt').value = defaultPrompts[currentPromptMode];
            customPrompt = defaultPrompts[currentPromptMode];
        }
    });
});

// Save settings
saveSettingsButton.addEventListener('click', () => {
    const customPromptText = document.getElementById('customPrompt').value.trim();
    customPrompt = customPromptText || defaultPrompts[currentPromptMode];
    refreshRate = document.getElementById('refreshRate').value || 1;
    settingsPanel.style.display = 'none';
    logMessage("Settings saved. Using " + currentPromptMode + " analysis mode.");
});

// capture_medal_set.js
// Takes a JSON string of medal IDs and captures the page.

const puppeteer = require('puppeteer');
const fs = require('fs');

const args = process.argv.slice(2);
const medalIds = JSON.parse(args[0]);

// Map medal IDs to the site's format (medal_id)
// The site uses query params like ?medal_id=123456789

(async () => {
    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();

    // Build the URL with medal IDs
    const baseUrl = 'https://ace-kyle.github.io/OPBR-medal-set-builder/';
    const url = `${baseUrl}?medal_id=${medalIds.join(',')}`;

    await page.goto(url, { waitUntil: 'networkidle2' });

    // Wait for the medal set to render
    await page.waitForSelector('.medal-set-detail .medal-display', { timeout: 10000 });

    // Find the "Download image" button and click it
    const downloadButton = await page.$('button.medal-set-detail-action-btn');
    if (downloadButton) {
        // Click the button to trigger the download
        await downloadButton.click();
    }

    // Wait for the download to finish (the site uses canvas to generate image)
    await page.waitForTimeout(2000);

    // The site usually downloads the image as a file.
    // To capture it, we need to intercept the download.
    // We'll use page._client() to intercept the download event.
    const client = await page.target().createCDPSession();
    await client.send('Browser.setDownloadBehavior', {
        behavior: 'allow',
        downloadPath: '/tmp',
    });

    // Re-trigger the download
    await downloadButton.click();

    // Wait for the download to complete
    await page.waitForTimeout(3000);

    // Find the downloaded file
    const files = fs.readdirSync('/tmp');
    let downloadedFile = files.find(f => f.startsWith('medal-set') && f.endsWith('.png'));

    if (!downloadedFile) {
        // Fallback: take a screenshot of the page
        await page.screenshot({ path: '/tmp/medal-set.png', fullPage: false });
        downloadedFile = 'medal-set.png';
    }

    console.log(`/tmp/${downloadedFile}`);

    await browser.close();
})();
